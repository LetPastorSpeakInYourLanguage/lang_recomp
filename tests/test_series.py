import sqlite3
import time

import pytest

from app import db, project, series, tasks


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")  # no downloads in tests
    db._local.c = None
    yield tmp_path
    db._local.c = None


def test_existing_projects_stay_standalone(fresh):
    c = sqlite3.connect(fresh / "t.db")  # a database from before series existed
    c.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT, src_lang TEXT DEFAULT 'en',"
              " tgt_lang TEXT DEFAULT 'am', max_speakers INTEGER, clip_start REAL, clip_end REAL, duration REAL,"
              " video TEXT, audio TEXT, created REAL, meta TEXT DEFAULT '{}')")
    c.execute("INSERT INTO projects (id,name,created) VALUES ('old','Old',0)")
    c.commit()
    c.close()
    p = project.summary("old")
    assert p["series_id"] is None and p["tgt_lang"] == "am"
    assert series.listing() == []


def test_new_sources_take_the_series_languages_and_settings(fresh):
    s = series.create("Sunday teachings", "speaker", "en", ["am", "om"], settings={"max_speakers": 1, "junk": 1})
    assert (s["label"], s["unit"], s["settings"]) == ("Speaker", "talk", {"max_speakers": 1})
    a = series.add_source(s["id"], "Talk 1", "https://youtu.be/a", origin_id="a")
    b = series.add_source(s["id"], "Talk 2", "https://youtu.be/b", origin_id="b")
    assert a["targets"] == ["am", "om"] and a["src_lang"] == "en" and a["max_speakers"] == 1
    assert [x["id"] for x in series.sources(s["id"])] == [a["id"], b["id"]]
    assert series.listing()[0]["counts"]["sources"] == 2
    with pytest.raises(ValueError):
        series.add_source(s["id"], "Talk 1 again", "https://youtu.be/a", origin_id="a")


def test_reorder_and_attach(fresh):
    s = series.create("Show", "show", targets=["ti"])
    a = series.add_source(s["id"], "Ep 1", "x")
    b = series.add_source(s["id"], "Ep 2", "y")
    assert [x["id"] for x in series.reorder(s["id"], [b["id"]])] == [b["id"], a["id"]]
    solo = project.create("Loose", "z", None, None, None)
    p = series.attach(solo["id"], s["id"])
    assert p["series_id"] == s["id"] and "ti" in p["targets"]  # the series' languages join its own
    assert [x["id"] for x in series.sources(s["id"])][-1] == solo["id"]
    assert series.attach(solo["id"], None)["series_id"] is None
    assert series.remove(s["id"]) == 2  # the grouping goes, the videos stay
    assert project.summary(a["id"])["series_id"] is None and series.listing() == []


def test_bad_kind_and_language_codes_are_refused(fresh):
    with pytest.raises(ValueError):
        series.create("X", "sitcom")
    with pytest.raises(ValueError):
        series.create("X", targets=["Amharic"])
    with pytest.raises(ValueError):
        series.create("X", targets=[])
    s = series.create("X")
    with pytest.raises(ValueError):
        series.update(s["id"], src_lang="English")
    assert series.update(s["id"], name=" Renamed ", feed_url="https://youtube.com/@x")["name"] == "Renamed"
