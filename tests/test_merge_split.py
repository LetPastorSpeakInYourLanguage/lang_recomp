import json
import time

import pytest

from app import db, project


@pytest.fixture()
def pid(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    pid = "t"
    db.run("INSERT INTO projects (id,name,created) VALUES (?,?,?)", pid, "t", time.time())
    words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("How are you today?".split())]
    db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text,words) VALUES (?,?,?,?,?,?,?)",
           pid, 1, "A", 0.0, 1.9, "How are you today?", json.dumps(words))
    project.set_translation(pid, 1, "am", "x")
    db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text,words) VALUES (?,?,?,?,?,?,?)",
           pid, 2, "B", 2.5, 3.0, "Fine.", json.dumps([{"w": "Fine.", "start": 2.5, "end": 3.0}]))
    yield pid
    db._local.c = None


def test_split_uses_word_times(pid):
    r = project.split(pid, 1, 2)
    s = {x["id"]: x for x in project.sentences(pid)}
    assert s[1]["text"] == "How are" and s[1]["end"] == 0.9
    assert s[r["second"]]["text"] == "you today?" and s[r["second"]]["start"] == 1.0
    assert s[r["second"]]["speaker"] == "A" and s[1]["tr"] == ""  # a split line needs a fresh translation


def test_split_rejects_edges(pid):
    for k in (0, 4):
        with pytest.raises(ValueError):
            project.split(pid, 1, k)


def test_merge_takes_longer_speaker_and_joins(pid):
    project.merge_next(pid, 1)
    s = project.sentences(pid)
    assert len(s) == 1 and s[0]["text"] == "How are you today? Fine."
    assert s[0]["speaker"] == "A" and s[0]["end"] == 3.0


def test_merge_then_split_round_trip(pid):
    project.merge_next(pid, 1)
    project.split(pid, 1, 4)
    assert [x["text"] for x in project.sentences(pid)] == ["How are you today?", "Fine."]


def test_merge_last_line_fails(pid):
    with pytest.raises(ValueError):
        project.merge_next(pid, 2)
