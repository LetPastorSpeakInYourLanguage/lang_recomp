import sqlite3
import time

import pytest

from app import chapters, db, project


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    yield tmp_path
    db._local.c = None


LINES = [(0.4, 1.0, "One."), (1.5, 3.0, "Two."), (3.5, 4.0, "Three."), (4.5, 6.0, "Four.")]


def _project(pid="p"):
    db.run("INSERT INTO projects (id,name,created,duration) VALUES (?,?,?,?)", pid, pid, time.time(), 8.0)
    for i, (a, b, t) in enumerate(LINES, 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", pid, i, "A", a, b, t)
    return pid


def _members(pid):
    return {s["id"]: s["chapter"] for s in project.sentences(pid)}


def test_first_chapter_opens_the_clip_and_holds_every_line(fresh):
    pid = _project()
    chs = chapters.listing(pid)
    assert [(c["index"], c["start"], c["end"], c["lines"]) for c in chs] == [(0, 0.0, 8.0, 4)]
    with pytest.raises(ValueError):
        chapters.toggle(pid, 1)  # the opening line cannot start a second chapter


def test_toggle_starts_and_folds_a_chapter(fresh):
    pid = _project()
    added = chapters.toggle(pid, 3)["added"]
    assert _members(pid) == {1: 1, 2: 1, 3: added, 4: added}
    heads = {s["id"]: s["chapter_head"] for s in project.sentences(pid)}
    assert heads == {1: 0, 2: 0, 3: 1, 4: 0}
    assert chapters.toggle(pid, 3) == {"removed": added}
    assert set(_members(pid).values()) == {1}


def test_merging_across_a_chapter_start_moves_it_to_the_next_line(fresh):
    pid = _project()
    cid = chapters.toggle(pid, 2)["added"]
    project.merge_next(pid, 1)  # line 2 (the chapter's opening line) joins line 1
    assert _members(pid) == {1: 1, 3: cid, 4: cid}
    assert next(c for c in chapters.listing(pid) if c["id"] == cid)["start"] == 3.5


def test_a_chapter_left_without_lines_is_dropped(fresh):
    pid = _project()
    chapters.toggle(pid, 4)
    project.merge_next(pid, 3)  # its only line merged into the previous chapter
    assert [c["id"] for c in chapters.listing(pid)] == [1]


def test_split_keeps_both_halves_in_the_chapter(fresh):
    pid = _project()
    db.run("UPDATE sentences SET text='Two words.' WHERE project_id=? AND id=2", pid)
    cid = chapters.toggle(pid, 2)["added"]
    r = project.split(pid, 2, 1)
    m = _members(pid)
    assert m[2] == cid and m[r["second"]] == cid


def test_ids_are_stable_and_titles_stick(fresh):
    pid = _project()
    a = chapters.toggle(pid, 2)["added"]
    b = chapters.toggle(pid, 4)["added"]
    chapters.rename(pid, b, "  Goodbyes ")
    chapters.toggle(pid, 2)  # folding an earlier chapter leaves later ids alone
    chs = chapters.listing(pid)
    assert [(c["id"], c["title"], c["index"]) for c in chs] == [(1, "", 0), (b, "Goodbyes", 1)]
    assert a not in {c["id"] for c in chs}


def test_translation_context_stops_at_chapters(fresh, monkeypatch):
    pid = _project()
    chapters.toggle(pid, 3)
    batches = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        def translate(self, items):
            batches.append([x["id"] for x in items])
            return {x["id"]: "t" for x in items}

    monkeypatch.setattr(project, "GoogleBatchTranslator", Fake)
    project._translate(pid, "am", None, False, lambda *a: None)
    assert batches == [[1, 2], [3, 4]]


def test_old_chapter_flags_become_chapters_once(fresh):
    c = sqlite3.connect(fresh / "t.db")
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO projects (id,name,created) VALUES ('p','p',0)")
    for i, (a, b, t) in enumerate(LINES, 1):
        # the flag on the opening line meant nothing in the old app either
        c.execute("INSERT INTO sentences (project_id,id,start,end,text,chapter_break) VALUES ('p',?,?,?,?,?)",
                  (i, a, b, t, int(i in (1, 3))))
    c.commit()
    c.close()
    chs = chapters.listing("p")
    assert [(c["id"], c["start"], c["lines"]) for c in chs] == [(1, 0.0, 2), (2, 3.5, 2)]
    assert db.row("SELECT SUM(chapter_break) n FROM sentences")["n"] == 0
    chapters.toggle("p", 3)  # the person removes it; migrating again must not bring it back
    db._local.c = None
    assert [c["id"] for c in chapters.listing("p")] == [1]
