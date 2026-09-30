"""Put the voice-path test's inputs and code in one folder the notebook can read.

    python spikes/voice_paths/prepare_inputs.py [--dest "G:/My Drive/LangBridge/experiments/voice_paths"] [--zip]

Reads the camille test clip from the app's library (read-only): the separated voice stem,
every line of a second or more with its Amharic translation, and each speaker's voice bank
and held-out spans from its last voice plan. Copies the runner and the worker's
omnivoice_gen.py / score.py beside them. ``--zip`` also writes voice_paths.zip (upload it to
Kaggle as a dataset). Only a few MB; nothing is run here.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PID = "camille-interview"
MIN_SLOT_S = 1.0  # shorter lines are interjections the pipeline keeps in the original voice


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="G:/My Drive/LangBridge/experiments/voice_paths")
    ap.add_argument("--zip", action="store_true")
    a = ap.parse_args()
    dest = Path(a.dest)
    proj = REPO / "data" / "projects" / PID
    plan = json.loads((proj / "voice_plan.json").read_text(encoding="utf-8"))

    db = sqlite3.connect(f"file:{REPO / 'data' / 'langbridge.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT s.id, s.speaker, s.start, s.end, s.text, tr.text AS am FROM sentences s"
                      " JOIN translations tr ON tr.project_id = s.project_id AND tr.sentence_id = s.id AND tr.lang = 'am'"
                      " WHERE s.project_id = ? ORDER BY s.start", (PID,)).fetchall()
    lines = [{"id": r["id"], "speaker": r["speaker"], "start": r["start"], "end": r["end"],
              "slot_s": round(r["end"] - r["start"], 3), "en": r["text"], "am": r["am"].strip()}
             for r in rows if r["am"] and r["am"].strip() and r["end"] - r["start"] >= MIN_SLOT_S
             and r["speaker"] in plan["characters"]]
    chars = {spk: {"bank": c["bank"], "bank_text": c["bank_text"], "heldout": c.get("heldout") or c["bank"]}
             for spk, c in plan["characters"].items()}

    (dest / "inputs").mkdir(parents=True, exist_ok=True)
    (dest / "code").mkdir(parents=True, exist_ok=True)
    shutil.copy(proj / "vocals.flac", dest / "inputs" / "vocals.flac")
    (dest / "inputs" / "lines.json").write_text(json.dumps({"clip": PID, "characters": chars, "lines": lines},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    for f in (HERE / "voice_paths.py", HERE / "svc_batch.py", REPO / "worker" / "lb_worker" / "tts" / "omnivoice_gen.py",
              REPO / "worker" / "lb_worker" / "tts" / "score.py"):
        shutil.copy(f, dest / "code" / f.name)
    shutil.copy(HERE / "voice_paths.ipynb", dest / "voice_paths.ipynb")
    print(f"{len(lines)} lines, speakers {sorted(chars)} -> {dest}")
    if a.zip:
        z = shutil.make_archive(str(dest.parent / "voice_paths"), "zip", dest.parent, dest.name)
        print("zip for Kaggle:", z)


if __name__ == "__main__":
    main()
