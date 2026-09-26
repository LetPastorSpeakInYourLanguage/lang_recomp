import sqlite3
import time

import pytest

from app import db, project
from app.translate.length import budget, detect_script, syllables


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    yield tmp_path
    db._local.c = None


def _project(pid="p", tgt="am"):
    db.run("INSERT INTO projects (id,name,created,tgt_lang) VALUES (?,?,?,?)", pid, pid, time.time(), tgt)
    for i, (a, b, t) in enumerate([(0.0, 1.0, "Hello."), (1.5, 3.0, "How are you?")], 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", pid, i, "A", a, b, t)
    return pid


def test_old_am_column_moves_into_translations_once(fresh):
    # A database from before languages were data: translations live in sentences.am.
    c = sqlite3.connect(fresh / "t.db")
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO projects (id,name,created,tgt_lang) VALUES ('p','p',0,'am')")
    c.execute("INSERT INTO sentences (project_id,id,start,end,text,am,am_locked) VALUES ('p',1,0,1,'Hi.','ሰላም',1)")
    c.execute("INSERT INTO sentences (project_id,id,start,end,text,am) VALUES ('p',2,1,2,'Bye.','ደህና')")
    c.commit()
    c.close()
    s = {x["id"]: x for x in project.sentences("p")}
    assert s[1]["tr"] == "ሰላም" and s[1]["tr_locked"] == 1 and s[1]["tr_provenance"] == "human"
    assert s[2]["tr"] == "ደህና" and s[2]["tr_provenance"] == "machine"
    assert db.row("SELECT am FROM sentences WHERE id=1")["am"] == ""  # moved, not copied twice
    db._local.c = None
    db.conn()  # migrating again is a no-op
    assert db.row("SELECT COUNT(*) n FROM translations")["n"] == 2


def test_languages_are_independent(fresh):
    pid = _project()
    project.add_target(pid, "om")
    project.set_translation(pid, 1, "am", "ሰላም")
    project.set_translation(pid, 1, "om", "Akkam.")
    assert project.sentences(pid)[0]["tr"] == "ሰላም"
    assert project.sentences(pid, "om")[0]["tr"] == "Akkam."
    assert project.sentences(pid, "om")[1]["tr"] == ""
    assert project.targets(pid) == ["am", "om"]
    counts = project.summary(pid)["counts"]["translated_by_lang"]
    assert counts == {"am": 1, "om": 1}


def test_machine_never_overwrites_a_person_unless_forced(fresh):
    pid = _project()
    project.set_translation(pid, 1, "am", "የሰው ትርጉም", locked=True, provenance="human")
    assert not project.set_translation(pid, 1, "am", "machine text", provenance="machine")
    assert project.sentences(pid)[0]["tr"] == "የሰው ትርጉም"
    project.set_translation(pid, 2, "am", "draft", provenance="machine")
    assert project.set_translation(pid, 2, "am", "better draft", provenance="machine")  # machine over machine: fine
    assert project.set_translation(pid, 1, "am", "forced", provenance="machine", force=True)
    assert project.sentences(pid)[0]["tr"] == "forced"


def test_merge_clears_every_language(fresh):
    pid = _project()
    project.set_translation(pid, 1, "am", "a")
    project.set_translation(pid, 2, "om", "b")
    project.merge_next(pid, 1)
    assert db.row("SELECT COUNT(*) n FROM translations WHERE project_id=?", pid)["n"] == 0


def test_translations_follow_their_line_to_a_new_id(fresh):
    pid = _project()
    project.set_translation(pid, 2, "am", "ሁለት")
    project._remap_lines(pid, {2: 7})
    assert db.row("SELECT text FROM translations WHERE sentence_id=7")["text"] == "ሁለት"
    assert db.row("SELECT COUNT(*) n FROM translations WHERE sentence_id=2")["n"] == 0


def test_language_codes_are_validated(fresh):
    pid = _project()
    with pytest.raises(ValueError):
        project.add_target(pid, "Amharic!")
    assert project.add_target(pid, "am") == ["am"]  # already the primary
    assert project.add_target(pid, "SW") == ["am", "sw"]


def test_syllables_by_script():
    assert syllables("ሰላም። እንዴት ነህ፧", "am") == 9
    assert syllables("Can you tell me a bit about yourself", "en") == 10
    assert syllables("Как дела") == 3 and detect_script("Как дела") == "cyrillic"
    assert syllables("你好世界") == 4
    assert budget("ሰላም እንዴት ነህ", 1.0, 5.0, "am")["ratio"] == 1.8
