"""Voice every line in its speaker's cloned voice, several takes each, scored.

Inputs: vocals.flac (the separated voice stem) and voice_plan.json:
  {"engine": {"model", "steps", "speed", "takes", "lang", "language", "asr"},
   "characters": {label: {"bank": [[s, e], ...], "bank_text": str, "heldout": [[s, e], ...]}},
   "lines": [{"id", "speaker", "text", "start", "end", "slot_s"}]}   ("am" in older plans)

Takes are written straight into the job folder's out/takes/, each renamed into place
only when complete, so a job that dies resumes where it stopped. Scores go to
out/scores.json and the per-line summary (best take chosen) to out/voice.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from ..deps import ensure
from ..registry import stage
from .bakeoff import TTS, pip, sh

DEFAULT_ENGINE = {"model": "k2-fsa/OmniVoice", "steps": 16, "speed": 1.4, "takes": 2,
                  "language": "Amharic", "asr": "badrex/Ethio-ASR-amharic"}


@stage("voice", model_key="omnivoice")
def voice(ctx) -> dict:
    ensure("soundfile", probe="soundfile")
    import soundfile as sf

    plan = json.loads(ctx.input(next(r for r in ctx.job["inputs"] if r.endswith("voice_plan.json")))
                      .read_text(encoding="utf-8"))
    engine = DEFAULT_ENGINE | plan.get("engine", {})
    vocals, sr = sf.read(ctx.input(next(r for r in ctx.job["inputs"] if r.endswith("vocals.flac"))),
                         dtype="float32", always_2d=True)
    vocals = vocals.mean(1)
    clips = ctx.work / "clips"
    clips.mkdir(exist_ok=True)

    def cut(s, e):
        return vocals[int(s * sr):int(e * sr)]

    bank, heldout = {}, {}
    for spk, c in plan["characters"].items():
        gap = np.zeros(int(0.25 * sr), dtype=np.float32)
        bank[spk] = clips / f"bank_{spk}.wav"
        sf.write(bank[spk], np.concatenate([np.concatenate([cut(s, e), gap]) for s, e in c["bank"]]), sr)
        heldout[spk] = []
        for k, (s, e) in enumerate(c.get("heldout") or c["bank"]):
            p = clips / f"held_{spk}_{k}.wav"
            sf.write(p, cut(s, e), sr)
            heldout[spk].append(str(p))

    takes_dir = ctx.drive_dir / "out" / "takes"  # final location: survives a crash
    takes_dir.mkdir(parents=True, exist_ok=True)
    for ln in plan["lines"]:  # plans written before languages were data say "am"
        ln.setdefault("text", ln.get("am", ""))
    items = []
    for ln in plan["lines"]:
        c = plan["characters"].get(ln["speaker"])
        if not c or not ln.get("text"):
            continue
        for k in range(int(engine["takes"])):
            items.append({"key": f"{ln['id']}_t{k}", "text": ln["text"], "ref_audio": str(bank[ln["speaker"]]),
                          "ref_text": c["bank_text"], "speed": engine["speed"], "seed": 1000 + k,
                          "out": str(takes_dir / f"{ln['id']}_t{k}.wav"), "skip_existing": True})
    todo = sum(1 for it in items if not Path(it["out"]).exists())
    ctx.set_progress(0.02, f"{len(plan['lines'])} lines, {len(items)} takes ({todo} to generate)")

    if todo:
        if not pip(ctx, "omnivoice"):
            raise RuntimeError("pip install omnivoice failed")
        man = ctx.work / "gen.json"
        man.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        res = ctx.work / "gen_res.json"
        p = sh([sys.executable, TTS / "omnivoice_gen.py", "--model", engine["model"], "--manifest", man,
                "--out", res, "--steps", str(engine["steps"]), "--language", engine["language"]],
               ctx, timeout=6 * 3600)
        if p.returncode:
            raise RuntimeError(f"generation failed (exit {p.returncode}); see log")
    made = [it for it in items if Path(it["out"]).exists()]
    ctx.set_progress(0.85, f"scoring {len(made)} takes")

    man = ctx.work / "score.json"
    by_id = {ln["id"]: ln for ln in plan["lines"]}
    man.write_text(json.dumps({"speakers": heldout, "items": [
        {"key": it["key"], "wav": it["out"], "speaker": by_id[int(it["key"].split("_t")[0])]["speaker"],
         "text": it["text"], "slot_s": by_id[int(it["key"].split("_t")[0])]["slot_s"]} for it in made]},
        ensure_ascii=False), encoding="utf-8")
    scores_path = ctx.out / "scores.json"
    p = sh([sys.executable, TTS / "score.py", "--manifest", man, "--out", scores_path, "--no-emotion",
            "--asr", engine.get("asr") or "none"], ctx)
    scores = json.loads(scores_path.read_text(encoding="utf-8"))["items"] if scores_path.exists() else {}

    summary = {}
    for ln in plan["lines"]:
        takes = []
        for it in made:
            if it["key"].startswith(f"{ln['id']}_t"):
                sc = scores.get(it["key"], {})
                takes.append({"take": int(it["key"].split("_t")[1]), "file": f"takes/{Path(it['out']).name}",
                              "text": ln["text"], **{k: sc.get(k) for k in ("sim", "cer", "dur", "dur_s", "asr")}})
        if takes:
            best = max(takes, key=take_score)
            summary[str(ln["id"])] = {"takes": takes, "best": best["take"]}
    (ctx.out / "voice.json").write_text(json.dumps({"engine": engine, "lines": summary}, ensure_ascii=False,
                                                   indent=1), encoding="utf-8")
    return {"lines": len(summary), "takes": len(made), "scored": bool(scores)}


def take_score(t: dict) -> float:
    """Higher is better: sounds like the speaker, says the text, fits the slot."""
    sim = t.get("sim") or 0.0
    cer = t.get("cer") if t.get("cer") is not None else 1.0
    dur = t.get("dur") or 1.0
    return sim - 0.6 * cer - 0.25 * max(0.0, dur - 1.15)
