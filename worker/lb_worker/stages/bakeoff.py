"""Amharic voice-cloning bake-off.

Inputs (job.json): vocals.flac, plan.json, and edge_<id>.mp3 files made on the desktop.

plan.json:
  {"items": [{"id", "speaker", "start", "end", "slot_s", "en", "am", "edge"}],
   "bank": {spk: [[start, end], ...]},        # clean clips -> 10 s timbre prompt
   "bank_text": {spk: "english words of the bank clips"},
   "heldout": {spk: [[start, end], ...]},     # for the similarity centroid only
   "systems": [...]}                          # optional subset

Each system runs in a subprocess so its package pins cannot break the worker or
each other. A system that fails (install, OOM, bad output) is recorded, not fatal.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from ..deps import cache_dir, ensure
from ..registry import stage

TTS = Path(__file__).resolve().parents[1] / "tts"
# fish_bank is opt-in (list it in plan["systems"]): its 5B weights need more system
# RAM than a free Colab runtime has, and running out kills the whole runtime.
DEFAULT_SYSTEMS = ["omni_bank", "omni_self_dur", "omniam_bank", "edge_raw", "edge_seedvc"]


def sh(cmd, ctx, cwd=None, timeout=3600) -> subprocess.CompletedProcess:
    """Run a command, streaming its output into the job log as it happens (the log
    reaches Drive with every heartbeat), so a runtime that dies mid-command still
    shows how far it got."""
    ctx.log("$ " + " ".join(str(c) for c in cmd)[:300])
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    lines: list[str] = []
    deadline = time.time() + timeout
    for line in p.stdout:
        line = line.rstrip()
        # Progress bars redraw with \r: keep only their final state.
        line = line.split("\r")[-1]
        if line:
            lines.append(line)
            if len(lines) <= 5000 and "%|" not in line:
                ctx.log("  | " + line[:300])
        if time.time() > deadline:
            p.kill()
            lines.append(f"killed after {timeout}s")
            break
    code = p.wait()
    out = "\n".join(lines)
    if code:
        ctx.log(f"exit {code}\n" + "\n".join(lines[-25:]))
    return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=out)


def pip(ctx, *specs):
    return sh([sys.executable, "-m", "pip", "install", "-q", *specs], ctx).returncode == 0



@stage("tts_bakeoff", model_key="bakeoff")
def tts_bakeoff(ctx) -> dict:
    ensure("soundfile", probe="soundfile")
    import soundfile as sf

    plan = json.loads(ctx.input(next(r for r in ctx.job["inputs"] if r.endswith("plan.json")))
                      .read_text(encoding="utf-8"))
    vocals, sr = sf.read(ctx.input(next(r for r in ctx.job["inputs"] if r.endswith("vocals.flac"))),
                         dtype="float32", always_2d=True)
    vocals = vocals.mean(1)
    clips = ctx.work / "clips"
    clips.mkdir(exist_ok=True)

    def cut(s, e):
        return vocals[int(s * sr):int(e * sr)]

    # prompts -------------------------------------------------------------------------------
    bank = {}
    for spk, ranges in plan["bank"].items():
        gap = np.zeros(int(0.25 * sr), dtype=np.float32)
        audio = np.concatenate([np.concatenate([cut(s, e), gap]) for s, e in ranges])
        bank[spk] = clips / f"bank_{spk}.wav"
        sf.write(bank[spk], audio, sr)
        shutil.copy(bank[spk], ctx.out / bank[spk].name)
    heldout = {}
    for spk, ranges in plan["heldout"].items():
        heldout[spk] = []
        for k, (s, e) in enumerate(ranges):
            p = clips / f"held_{spk}_{k}.wav"
            sf.write(p, cut(s, e), sr)
            heldout[spk].append(str(p))
    src = {}
    for it in plan["items"]:
        src[it["id"]] = clips / f"src_{it['id']}.wav"
        sf.write(src[it["id"]], cut(it["start"], it["end"]), sr)
        shutil.copy(src[it["id"]], ctx.out / src[it["id"]].name)

    systems = plan.get("systems") or DEFAULT_SYSTEMS
    # A resumed job starts from the out/ a dead session checkpointed: keep every
    # system that already finished cleanly.
    prev = ctx.out / "bakeoff.json"
    report = json.loads(prev.read_text(encoding="utf-8")) if prev.exists() else {}
    report = {"systems": report.get("systems", {}), "items": plan["items"]}
    for i, name in enumerate(systems):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        done = report["systems"].get(name)
        if done and "error" not in done and any(ctx.out.glob(f"{name}_*.wav")):
            ctx.log(f"{name}: already done in an earlier session, skipping")
            continue
        ctx.set_progress(i / (len(systems) + 1), f"system {name}")
        t0 = time.time()
        try:
            res = RUNNERS[name](ctx, plan, bank, src)
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
        res["wall_s"] = round(time.time() - t0, 1)
        report["systems"][name] = res
        ctx.log(f"{name}: {'ok' if 'error' not in res else res['error']} ({res['wall_s']}s)")
        (ctx.out / "bakeoff.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.checkpoint()

    # scoring -------------------------------------------------------------------------------
    ctx.set_progress(len(systems) / (len(systems) + 1), "scoring")
    items = []
    for name in systems:
        for it in plan["items"]:
            wav = ctx.out / f"{name}_{it['id']}.wav"
            if wav.exists():
                items.append({"key": f"{name}_{it['id']}", "wav": str(wav), "speaker": it["speaker"],
                              "text": it["am"], "slot_s": it["slot_s"], "source_wav": str(src[it["id"]])})
    man = ctx.work / "score_manifest.json"
    man.write_text(json.dumps({"speakers": heldout, "items": items}, ensure_ascii=False), encoding="utf-8")
    pip(ctx, "transformers>=4.44", "soundfile")
    p = sh([sys.executable, TTS / "score.py", "--manifest", man, "--out", ctx.out / "scores.json"], ctx)
    report["scoring"] = "ok" if p.returncode == 0 else "failed"
    (ctx.out / "bakeoff.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return {s: ("error" not in r) for s, r in report["systems"].items()} | {"scoring": report["scoring"]}


# ---- systems -----------------------------------------------------------------------------
def _omnivoice(ctx, plan, bank, src, model, name, self_ref=False, with_duration=False):
    if not pip(ctx, "omnivoice"):
        return {"error": "pip install omnivoice failed"}
    items = []
    for it in plan["items"]:
        use_self = self_ref and it["slot_s"] >= 2.5
        items.append({
            "key": it["id"], "text": it["am"],
            "ref_audio": str(src[it["id"]] if use_self else bank[it["speaker"]]),
            "ref_text": it["en"] if use_self else plan["bank_text"][it["speaker"]],
            "duration": it["slot_s"] if with_duration else None,
            "out": str(ctx.out / f"{name}_{it['id']}.wav"),
        })
    man = ctx.work / f"{name}.json"
    man.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    res_path = ctx.work / f"{name}_res.json"
    p = sh([sys.executable, TTS / "omnivoice_gen.py", "--model", model, "--manifest", man, "--out", res_path], ctx)
    if not res_path.exists():
        return {"error": f"omnivoice_gen exit {p.returncode}: {p.stderr[-600:]}"}
    res = json.loads(res_path.read_text(encoding="utf-8"))
    if not any(r.get("ok") for r in res.get("items", {}).values()):
        res["error"] = "no line produced audio: " + next(iter(res.get("items", {}).values()), {}).get("error", "")[-300:]
    return res


def omni_bank(ctx, plan, bank, src):
    return _omnivoice(ctx, plan, bank, src, "k2-fsa/OmniVoice", "omni_bank")


def omni_self_dur(ctx, plan, bank, src):
    """The sentence's own source audio as the prompt (carries its emotion) and the
    source slot length as a fixed duration."""
    return _omnivoice(ctx, plan, bank, src, "k2-fsa/OmniVoice", "omni_self_dur",
                      self_ref=True, with_duration=True)


def omniam_bank(ctx, plan, bank, src):
    return _omnivoice(ctx, plan, bank, src, "african-low-resource/omnivoice-amharic", "omniam_bank")


def edge_raw(ctx, plan, bank, src):
    """edge-tts made on the desktop, only resampled: the floor every clone must beat."""
    n = 0
    for it in plan["items"]:
        mp3 = ctx.input(it["edge"])
        if mp3.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-ac", "1", "-ar", "24000",
                            ctx.out / f"edge_raw_{it['id']}.wav"], check=True)
            n += 1
    return {"items": n}


SEEDVC = Path("/content/seed-vc")


# Seed-VC's requirements.txt pins 2024 versions (numpy 1.26, scipy 1.13, ...) that have
# no wheels for Colab's Python 3.13, so one bad pin fails the whole install. Install
# what inference.py actually imports, unpinned, on top of Colab's own torch stack.
SEEDVC_DEPS = ["munch", "einops", "descript-audio-codec", "pydub", "librosa", "hydra-core",
               "pyyaml", "python-dotenv", "huggingface-hub", "accelerate", "transformers", "soundfile"]


def _patch_bigvgan(ctx) -> None:
    """Seed-VC vendors BigVGAN, whose ``_from_pretrained`` declares ``proxies`` and
    ``resume_download`` as required keyword-only args; current huggingface_hub no
    longer passes them. Give them defaults instead of pinning an old hub."""
    import re

    for f in SEEDVC.rglob("bigvgan.py"):
        s = f.read_text(encoding="utf-8")
        s2 = re.sub(r"(\bproxies\s*:\s*[^,=)]+?)(\s*,)", r"\1 = None\2", s)
        s2 = re.sub(r"(\bresume_download\s*:\s*[^,=)]+?)(\s*,)", r"\1 = False\2", s2)
        if s2 != s:
            f.write_text(s2, encoding="utf-8")
            ctx.log(f"patched {f.relative_to(SEEDVC)} for current huggingface_hub")


def edge_seedvc(ctx, plan, bank, src):
    ready = SEEDVC / ".lb_ready"  # written only after a complete install
    if not ready.exists():
        # "Restart session" keeps /content, so a half-installed clone can survive:
        # never trust the folder alone.
        shutil.rmtree(SEEDVC, ignore_errors=True)
        if sh(["git", "clone", "--depth", "1", "https://github.com/Plachtaa/seed-vc", SEEDVC], ctx).returncode:
            return {"error": "clone failed"}
        if not pip(ctx, *SEEDVC_DEPS):
            return {"error": "pip install of Seed-VC dependencies failed (see log)"}
        _patch_bigvgan(ctx)
        # Seed-VC downloads into ./checkpoints: point that at the Drive cache.
        ck = SEEDVC / "checkpoints"
        shutil.rmtree(ck, ignore_errors=True)
        ck.symlink_to(cache_dir("seed-vc-checkpoints"), target_is_directory=True)
        ready.write_text("ok")
    per = {}
    for it in plan["items"]:
        if (ctx.out / f"edge_seedvc_{it['id']}.wav").exists():  # saved before a crash
            per[it["id"]] = {"ok": True, "resumed": True}
            continue
        raw = ctx.out / f"edge_raw_{it['id']}.wav"
        if not raw.exists():
            per[it["id"]] = {"ok": False, "error": "no edge_raw input"}
            continue
        od = ctx.work / f"svc_{it['id']}"
        shutil.rmtree(od, ignore_errors=True)
        od.mkdir()
        t = time.time()
        p = sh([sys.executable, "inference.py", "--source", raw, "--target", bank[it["speaker"]],
                "--output", od, "--diffusion-steps", "30", "--length-adjust", "1.0",
                "--inference-cfg-rate", "0.7", "--f0-condition", "False", "--auto-f0-adjust", "False",
                "--semi-tone-shift", "0", "--fp16", "True"], ctx, cwd=SEEDVC)
        wavs = sorted(od.glob("*.wav"), key=lambda f: f.stat().st_mtime)
        if wavs:
            shutil.move(str(wavs[-1]), ctx.out / f"edge_seedvc_{it['id']}.wav")
            per[it["id"]] = {"ok": True, "gen_s": round(time.time() - t, 2)}
            ctx.checkpoint()  # one sentence at a time reaches Drive
        else:
            per[it["id"]] = {"ok": False, "error": p.stderr[-400:]}
            if len(per) == 1:  # the first line failing means every line will: stop early
                return {"error": f"Seed-VC failed on the first line: {p.stderr[-300:]}", "items": per}
    return _summarise(per)


def _summarise(per: dict) -> dict:
    """A system counts as failed unless at least one line came out."""
    ok = sum(1 for r in per.values() if r.get("ok"))
    res = {"items": per, "ok_count": ok}
    if not ok:
        res["error"] = "no line produced audio: " + next(iter(per.values()), {}).get("error", "")[-300:]
    return res


FISH = Path("/content/fish-speech")


def fish_bank(ctx, plan, bank, src, limit=4):
    """Fish S2 Pro recommends 24 GB; on a T4 this may OOM, which is itself the answer."""
    ck = cache_dir("fish-s2-pro")  # 11 GB: kept on Drive, downloaded once
    if not (FISH / ".lb_ready").exists():
        shutil.rmtree(FISH, ignore_errors=True)
        if sh(["git", "clone", "--depth", "1", "https://github.com/fishaudio/fish-speech", FISH], ctx).returncode:
            return {"error": "clone failed"}
        if not pip(ctx, "-e", str(FISH)):
            return {"error": "pip install fish-speech failed"}
        (FISH / ".lb_ready").write_text("ok")
    if not (ck / "codec.pth").exists():
        pip(ctx, "huggingface_hub[cli]")
        if sh(["hf", "download", "fishaudio/s2-pro", "--local-dir", ck], ctx, timeout=3600).returncode:
            return {"error": "checkpoint download failed"}
    codec = ck / "codec.pth"
    prompt_tokens = {}
    for spk, wav in bank.items():
        p = sh([sys.executable, "fish_speech/models/dac/inference.py", "-i", wav, "--checkpoint-path", codec], ctx, cwd=FISH)
        if p.returncode or not (FISH / "fake.npy").exists():
            return {"error": f"reference encode failed: {p.stderr[-400:]}"}
        prompt_tokens[spk] = ctx.work / f"fish_prompt_{spk}.npy"
        shutil.move(str(FISH / "fake.npy"), prompt_tokens[spk])
    per = {}
    for it in plan["items"][:limit]:
        t = time.time()
        for f in FISH.glob("codes_*.npy"):
            f.unlink()
        p = sh([sys.executable, "fish_speech/models/text2semantic/inference.py", "--text", it["am"],
                "--prompt-text", plan["bank_text"][it["speaker"]], "--prompt-tokens", prompt_tokens[it["speaker"]],
                "--checkpoint-path", ck, "--half"], ctx, cwd=FISH)
        if p.returncode or not (FISH / "codes_0.npy").exists():
            err = p.stderr[-600:]
            per[it["id"]] = {"ok": False, "error": err}
            if "OutOfMemory" in err or "CUDA out of memory" in err:
                return {"error": "CUDA OOM on this GPU", "items": per}
            continue
        p = sh([sys.executable, "fish_speech/models/dac/inference.py", "-i", "codes_0.npy",
                "--checkpoint-path", codec], ctx, cwd=FISH)
        if (FISH / "fake.wav").exists():
            shutil.move(str(FISH / "fake.wav"), ctx.out / f"fish_bank_{it['id']}.wav")
            per[it["id"]] = {"ok": True, "gen_s": round(time.time() - t, 2)}
        else:
            per[it["id"]] = {"ok": False, "error": p.stderr[-400:]}
    return _summarise(per) | {"note": f"first {limit} sentences only (model reloads per call)"}


RUNNERS = {f.__name__: f for f in (omni_bank, omni_self_dur, omniam_bank, edge_raw, edge_seedvc, fish_bank)}
