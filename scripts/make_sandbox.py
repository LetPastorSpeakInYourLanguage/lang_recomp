"""Build a throwaway library for trying series, clips and recurring parts without
touching the real one:

    python scripts/make_sandbox.py            # → data/sandbox (replaced if it exists)
    python -m app --serve --port 8766 --data data/sandbox

It holds one synthetic show of three episodes (audio only, a few transcript lines
each). Every episode opens with the same 15 s "intro" after a cold open of a
different length and ends with the same 10 s "outro"; episode 3's copies are quieter
and noisy. Nothing is downloaded and no worker is needed.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sandbox"
SR = 22050


def chords(seed: int, seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(int(seconds / 0.4)):
        t = np.arange(int(0.4 * SR)) / SR
        notes = 220 * 2 ** (rng.integers(0, 24, 3) / 12)
        out.append(sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) for f in notes) * np.hanning(len(t)) ** 0.2)
    return np.concatenate(out).astype(np.float32)


def main() -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)
    os.environ["LANGBRIDGE_DATA"] = str(DATA)
    sys.path.insert(0, str(ROOT))
    from app import db, series, tasks

    tasks.start = lambda *a, **k: "sandbox"  # no import/download: audio is written below
    s = series.create("Sandbox show", "show", "en", ["am", "om"])
    intro, outro, rng = chords(1, 15), chords(2, 10), np.random.default_rng(3)
    for k, cold in enumerate((8.0, 20.0, 4.0)):
        noisy = k == 2
        i = 0.8 * intro + 0.05 * rng.standard_normal(len(intro)) if noisy else intro
        o = 0.8 * outro + 0.05 * rng.standard_normal(len(outro)) if noisy else outro
        audio = np.concatenate([chords(10 + k, cold), i, chords(20 + k, 40), o])
        p = series.add_source(s["id"], f"Episode {k + 1}", f"sandbox://episode-{k + 1}")
        d = DATA / "projects" / p["id"]
        d.mkdir(parents=True, exist_ok=True)
        wavfile.write(d / "clip.wav", SR, (audio / np.abs(audio).max() * 20000).astype(np.int16))
        dur = len(audio) / SR
        db.run("UPDATE projects SET audio=?, duration=? WHERE id=?", str(d / "clip.wav"), dur, p["id"])
        lines = [(0.5, 3.0, f"Previously, in episode {k}."), (cold + 16, cold + 19, "Welcome back to the show."),
                 (cold + 20, cold + 24, "Today we talk about hope."), (cold + 30, cold + 33, "Hope is a choice.")]
        for n, (a, b, t) in enumerate(lines, 1):
            db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)",
                   p["id"], n, "SPEAKER_00", a, b, t)
        db.run("INSERT INTO characters (project_id,label,name,important,color) VALUES (?,?,?,1,0)",
               p["id"], "SPEAKER_00", "Host")
    print(f"sandbox ready at {DATA}: series '{s['name']}' with 3 episodes")


if __name__ == "__main__":
    main()
