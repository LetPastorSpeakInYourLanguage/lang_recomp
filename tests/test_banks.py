import json

import numpy as np
import pytest
from scipy.io import wavfile

from app import banks, cast, db, project, series, tasks, voice


@pytest.fixture()
def show(tmp_path, monkeypatch):
    """Two episodes with vocal stems; the host is confirmed in both."""
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    s = series.create("Show", "show")
    ids = []
    for k in range(2):
        p = series.add_source(s["id"], f"Ep {k + 1}", f"x{k}")
        t = np.arange(40 * 16000) / 16000
        wavfile.write(project.pdir(p["id"]) / "v.wav", 16000, (np.sin(2 * np.pi * (200 + 50 * k) * t) * 8000).astype(np.int16))
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(project.pdir(p["id"]) / "v.wav"),
                        str(project.pdir(p["id"]) / "vocals.flac")], check=True)
        for i, (a, b, txt) in enumerate([(1, 4, "A clean line."), (5, 11, "Another clean line here."),
                                         (12, 14.5, "no punctuation here"), (15, 30, "Far too long a line.")], 1):
            db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)",
                   p["id"], i, "SPEAKER_00", a, b, txt)
        (project.pdir(p["id"]) / "diarization.json").write_text(json.dumps({"centroids": {}}))
        cast.ensure_for_source(p["id"], {"SPEAKER_00": 30.0})
        ids.append(p["id"])
    host = cast.for_source(ids[0])[0]["uid"]
    cast.link(ids[1], "SPEAKER_00", host)
    yield host, ids
    db._local.c = None


def test_the_bank_draws_on_every_episode_and_lives_with_the_character(show):
    host, ids = show
    rows = banks.rebuild(host)
    bank = [r for r in rows if r["role"] == "bank"]
    assert {r["source_id"] for r in bank} == set(ids)  # sources take turns
    assert 9 <= sum(r["end"] - r["start"] for r in bank) <= 18
    assert all(r["text"].endswith(".") for r in bank)  # clean lines only in the bank
    assert not any(r["line_id"] == 4 for r in rows)  # 15 s: too long to sample
    assert all("works" in r["path"] and r["path"].endswith(".flac") for r in rows)


def test_a_persons_pin_and_exclusion_survive_a_rebuild(show):
    host, ids = show
    banks.rebuild(host)
    banks.pin(host, ids[0], 3, "bank")         # the unpunctuated line, on purpose
    banks.pin(host, ids[1], 2, "excluded")     # a line they do not want
    rows = {(r["source_id"], r["line_id"]): r for r in banks.rebuild(host)}
    assert rows[(ids[0], 3)]["role"] == "bank" and rows[(ids[0], 3)]["manual"]
    assert rows[(ids[1], 2)]["role"] == "excluded"
    with pytest.raises(ValueError):
        banks.pin(host, ids[0], 4)  # not a usable line


def test_a_voice_job_ships_the_characters_bank(show, tmp_path):
    host, ids = show
    plan = voice.characters_plan(ids[1], tmp_path / "jobfiles")
    entry = plan["SPEAKER_00"]
    assert entry["bank_file"] == "bank_SPEAKER_00.wav" and entry["sources"] == 2
    assert (tmp_path / "jobfiles" / entry["bank_file"]).stat().st_size > 100_000
    assert all((tmp_path / "jobfiles" / f).exists() for f in entry["heldout_files"])
    assert entry["bank"]  # the old span form is still there for older workers
