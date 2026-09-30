"""Voice-path test on the camille clip: OmniVoice cloning vs native Amharic speech + Seed-VC.

    python voice_paths.py --folder <experiment folder> [--work /content/vp] [--systems a b ...]

<folder>/inputs/  vocals.flac, lines.json (made on the PC by prepare_inputs.py)
<folder>/code/    this file, svc_batch.py, omnivoice_gen.py, score.py
<folder>/results/ takes/<system>/<line>.wav, scores.json, summary.md, listen.html

Path 1, OmniVoice cloning from the speaker's English lines:
  omni_today         today's settings: the character's bank (clips glued with 0.25 s gaps), 1.4x
  omni_tight         the same bank with its inner pauses squeezed to 60 ms and no glue gaps
  omni_tight_punct   + Amharic punctuation (English commas -> ፣, a final ።)
Path 2, native Amharic speech, then Seed-VC to the speaker's voice (timbre only):
  edge, mms, native  the native speech alone (edge-tts Ameha/Mekdes; Meta MMS-TTS; OmniVoice-Amharic
                     prompted with a native Amharic speaker of the same gender)
  <base>_xlsr / <base>_whisper   converted by Seed-VC v1 (fast XLS-R model / Whisper-small model)

Every system is resumable (takes already made are kept) and a failing system is recorded,
not fatal. Scores: likeness to the speaker (WavLM), back-transcription CER (Ethio-ASR),
length vs the English slot, pauses per 10 words, and pauses the Amharic punctuation does
not explain ("stray" pauses, the problem this test is about).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

CODE = Path(__file__).resolve().parent
OMNI, OMNI_AM = "k2-fsa/OmniVoice", "african-low-resource/omnivoice-amharic"
EDGE_VOICE = {"male": "am-ET-AmehaNeural", "female": "am-ET-MekdesNeural"}
ASR = "badrex/Ethio-ASR-amharic"
BENCH = "addisai/amharic-tts-benchmark"  # public; human reference clips = native Amharic speakers
SEEDVC_REPO = "https://github.com/Plachtaa/seed-vc"
BASES = ["edge", "mms", "native"]
VC = ["xlsr", "whisper"]
ALL = ["omni_today", "omni_tight", "omni_tight_punct"] + [f"{b}{s}" for b in BASES for s in ("", "_xlsr", "_whisper")]
GROUPS = [("Path 1: OmniVoice cloning", ["omni_today", "omni_tight", "omni_tight_punct"])] + [
    (f"Path 2: {b} → Seed-VC", [b, f"{b}_xlsr", f"{b}_whisper"]) for b in BASES]
PUNCT = "፣።፤፥፦፧፨,.!?;:"


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def sh(cmd: list, cwd=None) -> int:
    log("$ " + " ".join(str(c) for c in cmd)[:240])
    return subprocess.run([str(c) for c in cmd], cwd=cwd).returncode


def pip(*specs: str) -> None:
    sh([sys.executable, "-m", "pip", "install", "-q", *specs])


# ---- audio helpers ---------------------------------------------------------------------------
def frames_db(x: np.ndarray, sr: int, hop_s: float = 0.01) -> np.ndarray:
    hop = max(1, int(sr * hop_s))
    n = len(x) // hop
    e = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    return 20 * np.log10(e / (e.max() + 1e-12))


def inner_pauses(x: np.ndarray, sr: int, thr: float = -38, min_s: float = 0.15) -> list[tuple[float, float]]:
    """Silences of at least ``min_s`` between the first and last sound: (start, length) in s."""
    if len(x) < sr * 0.1:
        return []
    db = frames_db(x, sr)
    sp = np.where(db >= thr)[0]
    if len(sp) == 0:
        return []
    sil = list(db[sp[0]:sp[-1] + 1] < thr) + [False]
    out, run = [], 0
    for i, s in enumerate(sil):
        if s:
            run += 1
        else:
            if run * 0.01 >= min_s:
                out.append((round((sp[0] + i - run) * 0.01, 2), round(run * 0.01, 2)))
            run = 0
    return out


def squeeze_pauses(x: np.ndarray, sr: int, keep_s: float = 0.06, thr: float = -38, min_s: float = 0.12) -> np.ndarray:
    """Shorten every inner silence longer than ``min_s`` to ``keep_s``; trim the ends."""
    db = frames_db(x, sr)
    hop = int(sr * 0.01)
    sp = np.where(db >= thr)[0]
    if len(sp) == 0:
        return x
    x = x[sp[0] * hop:(sp[-1] + 1) * hop]
    db = db[sp[0]:sp[-1] + 1]
    keep, run_start = np.ones(len(x), dtype=bool), None
    for i, s in enumerate(list(db < thr) + [False]):
        if s and run_start is None:
            run_start = i
        elif not s and run_start is not None:
            if (i - run_start) * 0.01 >= min_s:
                cut_from = run_start * hop + int(keep_s * sr / 2)
                cut_to = i * hop - int(keep_s * sr / 2)
                keep[cut_from:cut_to] = False
            run_start = None
    return x[keep]


def to_mono(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    return x.mean(1), sr


def decode(src: Path, dst: Path, sr: int = 24000) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(sr), str(dst)], check=True)


def median_f0(x: np.ndarray, sr: int) -> float:
    import librosa

    y = librosa.resample(x, orig_sr=sr, target_sr=16000)[: 16000 * 20]
    f0, voiced, _ = librosa.pyin(y, fmin=60, fmax=400, sr=16000)
    f0 = f0[voiced & ~np.isnan(f0)]
    return float(np.median(f0)) if len(f0) else 0.0


def gender_of(f0: float) -> str:
    return "female" if f0 >= 165 else "male"


# ---- text ---------------------------------------------------------------------------------
def fix_punct(am: str) -> str:
    """Amharic punctuation the voice model phrases by: English commas and semicolons
    become ፣ and ፤, a sentence ends with ። (questions and exclamations keep theirs)."""
    t = re.sub(r"\s*,\s*", "፣ ", am.strip())
    t = re.sub(r"\s*;\s*", "፤ ", t)
    if t.endswith(("...", "…")):  # a trailing-off sentence stays one
        return t
    t = re.sub(r"\.$", "።", t).strip()
    if t and t[-1] not in "።?!፧":
        t += "።"
    return t


def inner_punct(text: str) -> int:
    return sum(1 for ch in text.rstrip(PUNCT + " …") if ch in PUNCT)


# ---- the run --------------------------------------------------------------------------------
class Test:
    def __init__(self, folder: Path, work: Path, systems: list[str], steps: int):
        self.folder, self.work, self.systems, self.steps = folder, work, systems, steps
        self.inp, self.res = folder / "inputs", folder / "results"
        self.takes = self.res / "takes"
        self.work.mkdir(parents=True, exist_ok=True)
        self.takes.mkdir(parents=True, exist_ok=True)
        self.data = json.loads((self.inp / "lines.json").read_text(encoding="utf-8"))
        self.lines = self.data["lines"]
        for ln in self.lines:
            ln["am_fix"] = fix_punct(ln["am"])
        self.timing: dict[str, float] = {}
        tf = self.res / "timing.json"
        if tf.exists():
            self.timing = json.loads(tf.read_text(encoding="utf-8"))
        self.errors: dict[str, str] = {}

    def want(self, *names: str) -> bool:
        return any(n in self.systems for n in names)

    def out(self, system: str, ln: dict) -> Path:
        return self.takes / system / f"{ln['id']:03d}.wav"

    def done(self, system: str) -> bool:
        return all(self.out(system, ln).exists() for ln in self.lines)

    def timed(self, name: str, fn) -> None:
        t = time.time()
        try:
            fn()
        except Exception as e:  # one system failing must not stop the others
            self.errors[name] = f"{type(e).__name__}: {e}"
            log(f"{name} FAILED: {e}")
        self.timing[name] = self.timing.get(name, 0) + round(time.time() - t, 1)
        (self.res / "timing.json").write_text(json.dumps(self.timing, indent=1), encoding="utf-8")

    # -- inputs
    def prepare(self) -> None:
        v, sr = to_mono(self.inp / "vocals.flac")
        refs = self.res / "refs"
        refs.mkdir(exist_ok=True)
        cut = lambda s, e: v[int(s * sr):int(e * sr)]  # noqa: E731
        gap, tight_gap = np.zeros(int(0.25 * sr), np.float32), np.zeros(int(0.06 * sr), np.float32)
        self.bank, self.tight, self.held, self.gender = {}, {}, {}, {}
        for spk, c in self.data["characters"].items():
            clips = [cut(s, e) for s, e in c["bank"]]
            bank = np.concatenate([np.concatenate([x, gap]) for x in clips])  # as the pipeline makes it
            tight = np.concatenate([np.concatenate([squeeze_pauses(x, sr), tight_gap]) for x in clips])
            self.bank[spk], self.tight[spk] = refs / f"bank_{spk}.wav", refs / f"bank_tight_{spk}.wav"
            sf.write(self.bank[spk], bank, sr)
            sf.write(self.tight[spk], tight, sr)
            self.held[spk] = []
            for k, (s, e) in enumerate(c["heldout"]):
                p = refs / f"held_{spk}_{k}.wav"
                sf.write(p, cut(s, e), sr)
                self.held[spk].append(str(p))
            f0 = median_f0(bank, sr)
            self.gender[spk] = c.get("gender") or gender_of(f0)
            log(f"{spk} ({c.get('name') or '?'}): median pitch {f0:.0f} Hz -> {self.gender[spk]}; bank "
                f"{len(bank) / sr:.1f} s with {len(inner_pauses(bank, sr))} pauses, tight bank "
                f"{len(tight) / sr:.1f} s with {len(inner_pauses(tight, sr))}")
        for ln in self.lines:  # the English original, for listening
            p = refs / f"src_{ln['id']:03d}.wav"
            if not p.exists():
                sf.write(p, cut(ln["start"], ln["end"]), sr)

    def native_refs(self) -> None:
        """A native Amharic speaker per gender: human clips from Addis AI's public benchmark
        (FLEURS / WAXAL / Horn-ASR recordings), 4-10 s, the fewest pauses per second."""
        f = self.res / "refs" / "native.json"
        if f.exists():
            self.natives = json.loads(f.read_text(encoding="utf-8"))
            return
        from huggingface_hub import hf_hub_download

        meta = hf_hub_download(BENCH, "audio/metadata.csv", repo_type="dataset")
        rows = [r for r in csv.DictReader(open(meta, encoding="utf-8")) if r["system"] == "human-reference"]
        cands = {"male": [], "female": []}
        for r in rows[:60]:
            try:
                p = hf_hub_download(BENCH, "audio/" + r["file_name"], repo_type="dataset")
                x, sr = to_mono(Path(p))
                dur = len(x) / sr
                if not 4 <= dur <= 10:
                    continue
                g = gender_of(median_f0(x, sr))
                rate = len(inner_pauses(x, sr)) / dur
                cands[g].append((rate, -dur, p, r["reference_text"], r["case_id"]))
            except Exception as e:
                log(f"skipping {r['file_name']}: {e}")
        self.natives = {}
        for g in ("male", "female"):
            pool = sorted(cands[g]) or sorted(cands["male"] + cands["female"])
            rate, _, p, text, case = pool[0]
            dst = self.res / "refs" / f"native_{g}.wav"
            x, sr = to_mono(Path(p))
            sf.write(dst, x, sr)
            self.natives[g] = {"wav": str(dst), "text": text, "case": case, "pauses_per_s": round(rate, 2)}
            log(f"native {g} voice: {case} ({len(cands[g])} candidates), {rate:.2f} pauses/s")
        f.write_text(json.dumps(self.natives, ensure_ascii=False, indent=1), encoding="utf-8")

    # -- path 1 and the native OmniVoice base
    def omnivoice(self) -> None:
        todo = []
        for ln in self.lines:
            spk = ln["speaker"]
            bank_text = self.data["characters"][spk]["bank_text"]
            variants = {"omni_today": (self.bank[spk], ln["am"]), "omni_tight": (self.tight[spk], ln["am"]),
                        "omni_tight_punct": (self.tight[spk], ln["am_fix"])}
            for name, (ref, text) in variants.items():
                if name in self.systems:
                    todo.append({"key": f"{name}|{ln['id']}", "text": text, "ref_audio": str(ref), "ref_text": bank_text,
                                 "speed": 1.4, "seed": 1000, "out": str(self.out(name, ln)), "skip_existing": True})
        self._omni_run(OMNI, todo, "omni")

    def gen_native(self) -> None:
        todo = [{"key": f"native|{ln['id']}", "text": ln["am_fix"], "seed": 1000, "speed": 1.0, "skip_existing": True,
                 "ref_audio": self.natives[self.gender[ln["speaker"]]]["wav"],
                 "ref_text": self.natives[self.gender[ln["speaker"]]]["text"], "out": str(self.out("native", ln))}
                for ln in self.lines]
        self._omni_run(OMNI_AM, todo, "native")

    def _omni_run(self, model: str, items: list[dict], tag: str) -> None:
        items = [it for it in items if not Path(it["out"]).exists()]
        if not items:
            return
        for it in items:
            Path(it["out"]).parent.mkdir(parents=True, exist_ok=True)
        man = self.work / f"{tag}.json"
        man.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        code = sh([sys.executable, CODE / "omnivoice_gen.py", "--model", model, "--manifest", man,
                   "--out", self.work / f"{tag}_res.json", "--steps", "16", "--language", "Amharic"])
        if code:
            raise RuntimeError(f"omnivoice_gen exit {code}")

    # -- path 2 bases
    def edge(self) -> None:
        import edge_tts

        async def one(ln):
            dst = self.out("edge", ln)
            if dst.exists():
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            mp3 = self.work / f"edge_{ln['id']}.mp3"
            await edge_tts.Communicate(ln["am_fix"], EDGE_VOICE[self.gender[ln["speaker"]]]).save(str(mp3))
            decode(mp3, dst)

        async def run_all():
            for ln in self.lines:
                await one(ln)

        asyncio.run(run_all())

    def mms(self) -> None:
        import torch
        import uroman as ur
        from transformers import AutoTokenizer, VitsModel

        dev = "cuda" if torch.cuda.is_available() else "cpu"
        tok = AutoTokenizer.from_pretrained("facebook/mms-tts-amh")
        model = VitsModel.from_pretrained("facebook/mms-tts-amh").to(dev).eval()
        rom = ur.Uroman()
        for ln in self.lines:
            dst = self.out("mms", ln)
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = rom.romanize_string(ln["am_fix"], lcode="amh")
            torch.manual_seed(0)  # VITS draws its durations: the same take on a re-run
            with torch.no_grad():
                wav = model(**tok(text, return_tensors="pt").to(dev)).waveform[0].cpu().numpy()
            sf.write(dst, wav, model.config.sampling_rate)
        del model
        torch.cuda.empty_cache()

    # -- Seed-VC
    def seedvc_setup(self) -> Path:
        d = self.work / "seed-vc"
        ready = d / ".lb_ready"
        if ready.exists():
            return d
        shutil.rmtree(d, ignore_errors=True)
        if sh(["git", "clone", "--depth", "1", SEEDVC_REPO, d]):
            raise RuntimeError("git clone seed-vc failed")
        pip("munch", "einops")
        pip("--no-deps", "descript-audio-codec")
        # Seed-VC's vendored BigVGAN wants arguments current huggingface_hub no longer passes
        for f in d.rglob("bigvgan.py"):
            s = f.read_text(encoding="utf-8")
            s2 = re.sub(r"(\bproxies\s*:\s*[^,=)]+?)(\s*,)", r"\1 = None\2", s)
            s2 = re.sub(r"(\bresume_download\s*:\s*[^,=)]+?)(\s*,)", r"\1 = False\2", s2)
            f.write_text(s2, encoding="utf-8")
        shutil.copy(CODE / "svc_batch.py", d / "svc_batch.py")
        ready.write_text("ok")
        return d

    def seedvc(self, model: str) -> None:
        items = []
        for base in BASES:
            name = f"{base}_{model}"
            if name not in self.systems:
                continue
            for ln in self.lines:
                src = self.out(base, ln)
                if src.exists():
                    items.append({"key": f"{name}|{ln['id']}", "source": str(src), "out": str(self.out(name, ln)),
                                  "target": str(self.bank[ln["speaker"]])})
        items = [it for it in items if not Path(it["out"]).exists()]
        if not items:
            return
        d = self.seedvc_setup()
        man = self.work / f"svc_{model}.json"
        man.write_text(json.dumps(items), encoding="utf-8")
        code = sh([sys.executable, "svc_batch.py", "--model", model, "--manifest", man,
                   "--out", self.work / f"svc_{model}_res.json", "--steps", str(self.steps)], cwd=d)
        if code:
            raise RuntimeError(f"svc_batch exit {code}")

    # -- scores
    def score(self) -> dict:
        items = []
        for name in self.systems:
            for ln in self.lines:
                p = self.out(name, ln)
                if p.exists():
                    items.append({"key": f"{name}|{ln['id']}", "wav": str(p), "speaker": ln["speaker"],
                                  "text": self.text_of(name, ln), "slot_s": ln["slot_s"]})
        man = self.work / "score.json"
        man.write_text(json.dumps({"speakers": self.held, "items": items}, ensure_ascii=False), encoding="utf-8")
        out = self.res / "scores.json"
        sh([sys.executable, CODE / "score.py", "--manifest", man, "--out", out, "--no-emotion", "--asr", ASR])
        sc = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"items": {}}
        for it in items:  # the pause measures
            x, sr = to_mono(Path(it["wav"]))
            ps = inner_pauses(x, sr)
            name, lid = it["key"].split("|")
            ln = next(l for l in self.lines if str(l["id"]) == lid)
            r = sc["items"].setdefault(it["key"], {})
            r.setdefault("dur_s", round(len(x) / sr, 2))  # also when the scorer failed
            r.setdefault("dur", round(len(x) / sr / ln["slot_s"], 2))
            r["pauses"] = ps
            r["words"] = len(it["text"].split())
            r["stray"] = max(0, len(ps) - inner_punct(it["text"]))
        out.write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
        return sc

    def text_of(self, name: str, ln: dict) -> str:
        return ln["am"] if name in ("omni_today", "omni_tight") else ln["am_fix"]

    # -- report
    def report(self, sc: dict) -> None:
        rows = []
        for name in self.systems:
            rs = [sc["items"].get(f"{name}|{ln['id']}") for ln in self.lines]
            rs = [r for r in rs if r and "error" not in r and "pauses" in r]
            if not rs:
                rows.append({"system": name, "takes": 0, "error": self.errors.get(name, "no takes")})
                continue
            def mean(k, rs=rs):
                v = [r[k] for r in rs if r.get(k) is not None]
                return round(float(np.mean(v)), 3) if v else None
            words = sum(r["words"] for r in rs)
            rows.append({"system": name, "takes": len(rs), "likeness": mean("sim"), "cer": mean("cer"),
                         "length_vs_slot": mean("dur"),
                         "pauses_per_10_words": round(10 * sum(len(r["pauses"]) for r in rs) / max(1, words), 2),
                         "stray_pauses": sum(r["stray"] for r in rs),
                         "seconds": self.timing.get(self.stage_of(name))})
        summary = {"rows": rows, "real_likeness": sc.get("real_sim"), "genders": self.gender,
                   "native_refs": getattr(self, "natives", None), "errors": self.errors}
        (self.res / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        head = ["system", "takes", "likeness", "cer", "length_vs_slot", "pauses_per_10_words", "stray_pauses", "seconds",
                "error"]
        md = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        md += ["| " + " | ".join(str(r.get(h) if r.get(h) is not None else "–") for h in head) + " |" for r in rows]
        md.append(f"\nReal speech likeness (held-out clips vs their speaker): {sc.get('real_sim')}")
        (self.res / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print("\n".join(md))
        self.page(sc, rows)

    def stage_of(self, name: str) -> str:
        if name.startswith("omni_"):
            return "omnivoice"
        for m in VC:
            if name.endswith("_" + m):
                return f"seedvc_{m}"
        return name

    def page(self, sc: dict, rows: list[dict]) -> None:
        rel = lambda p: os.path.relpath(p, self.res).replace(os.sep, "/")  # noqa: E731
        e = html.escape
        th = "".join(f"<th>{e(h)}</th>" for h in ["system", "takes", "likeness", "CER", "length / slot",
                                                   "pauses per 10 words", "stray pauses", "seconds", "error"])
        trs = "".join("<tr>" + "".join(f"<td>{e(str(r.get(k) if r.get(k) is not None else '–'))}</td>" for k in
                                       ["system", "takes", "likeness", "cer", "length_vs_slot", "pauses_per_10_words",
                                        "stray_pauses", "seconds", "error"]) + "</tr>" for r in rows)
        blocks = []
        for ln in self.lines:
            cells = []
            for title, names in GROUPS:
                items = []
                for n in names:
                    if n not in self.systems or not self.out(n, ln).exists():
                        continue
                    r = sc["items"].get(f"{n}|{ln['id']}", {})
                    note = (f"like {r.get('sim', '–')} · CER {r.get('cer', '–')} · {len(r.get('pauses', []))} pauses"
                            f" ({r.get('stray', '–')} stray) · {r.get('dur_s', '–')} s")
                    items.append(f"<div class=take><b>{e(n)}</b><audio controls preload=none "
                                 f"src='{e(rel(self.out(n, ln)))}'></audio><small>{e(note)}</small></div>")
                if items:
                    cells.append(f"<div class=group><h4>{e(title)}</h4>{''.join(items)}</div>")
            src = self.res / "refs" / f"src_{ln['id']:03d}.wav"
            blocks.append(
                f"<section><h3>#{ln['id']} · {e(ln['speaker'])} · {ln['slot_s']} s</h3>"
                f"<p class=en>{e(ln['en'])}</p><p class=am>{e(ln['am'])}<br><span>fixed: {e(ln['am_fix'])}</span></p>"
                f"<div class=take><b>English original</b><audio controls preload=none src='{e(rel(src))}'></audio></div>"
                f"<div class=groups>{''.join(cells)}</div></section>")
        doc = f"""<!doctype html><meta charset=utf-8><title>Voice paths</title>
<style>
body{{font:14px system-ui,sans-serif;margin:16px;max-width:1300px;background:#fff;color:#111}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}}td:first-child{{text-align:left}}
section{{border-top:2px solid #ddd;margin-top:18px}}.en{{color:#555}}.am{{font-size:16px}}.am span{{font-size:13px;color:#777}}
.groups{{display:flex;flex-wrap:wrap;gap:10px}}.group{{border:1px solid #ddd;border-radius:6px;padding:6px;flex:1 1 380px}}
.group h4{{margin:2px 0 6px}}.take{{margin:4px 0}}.take b{{display:inline-block;width:130px}}audio{{height:30px;vertical-align:middle}}
small{{display:block;color:#666;margin-left:134px}}
@media (prefers-color-scheme: dark){{body{{background:#161616;color:#eee}}td,th,.group{{border-color:#444}}.en,small,.am span{{color:#aaa}}}}
</style>
<h1>Voice paths — camille clip</h1>
<p><b>likeness</b>: sounds like the speaker (real speech of the same speaker scores {e(str(sc.get('real_sim')))}).
<b>CER</b>: share of characters the Amharic recogniser gets wrong (lower is better).
<b>length / slot</b>: take length ÷ English line length. <b>stray pauses</b>: pauses where the Amharic has no punctuation.
<b>seconds</b>: time of the stage that made it, model loading included (the three OmniVoice systems share one stage).</p>
<table><tr>{th}</tr>{trs}</table>
{''.join(blocks)}"""
        (self.res / "listen.html").write_text(doc, encoding="utf-8")
        log(f"listening page: {self.res / 'listen.html'}")

    # -- all of it
    def run(self) -> None:
        pip("omnivoice", "edge-tts", "uroman", "librosa", "huggingface_hub")
        self.prepare()
        if self.want("native", "native_xlsr", "native_whisper"):
            self.timed("native_refs", self.native_refs)
        if self.want("omni_today", "omni_tight", "omni_tight_punct"):
            self.timed("omnivoice", self.omnivoice)
        if self.want("native", "native_xlsr", "native_whisper") and hasattr(self, "natives"):
            self.timed("native", self.gen_native)
        if self.want("edge", "edge_xlsr", "edge_whisper"):
            self.timed("edge", self.edge)
        if self.want("mms", "mms_xlsr", "mms_whisper"):
            self.timed("mms", self.mms)
        for m in VC:
            if any(f"{b}_{m}" in self.systems for b in BASES):
                self.timed(f"seedvc_{m}", lambda m=m: self.seedvc(m))
        self.report(self.score())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--work", default="/content/vp-work" if Path("/content").exists() else "vp-work")
    ap.add_argument("--systems", nargs="*", default=ALL)
    ap.add_argument("--steps", type=int, default=25, help="Seed-VC diffusion steps")
    a = ap.parse_args()
    bad = set(a.systems) - set(ALL)
    if bad:
        raise SystemExit(f"unknown systems {sorted(bad)}; known: {ALL}")
    Test(Path(a.folder), Path(a.work), a.systems, a.steps).run()


if __name__ == "__main__":
    main()
