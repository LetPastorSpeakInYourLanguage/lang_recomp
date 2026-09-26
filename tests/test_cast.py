import json
import sqlite3
import time

import numpy as np
import pytest

from app import cast, db, project, series, tasks

RNG = np.random.default_rng(0)
NEIL, BETH, GUEST = (RNG.standard_normal(256) for _ in range(3))  # three distinct voices


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    yield tmp_path
    db._local.c = None


def _episode(sid, name, voices: dict[str, np.ndarray], talk=30.0):
    """A source whose diarizer found these voices (centroid = voice + a little noise)."""
    p = series.add_source(sid, name, f"https://youtu.be/{name}") if sid else project.create(name, "x", None, None, None)
    cen = {lab: (v + 0.15 * RNG.standard_normal(256)).round(5).tolist() for lab, v in voices.items()}
    (project.pdir(p["id"]) / "diarization.json").write_text(json.dumps({"centroids": cen}))
    for i, lab in enumerate(voices, 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)",
               p["id"], i, lab, i * 2.0, i * 2.0 + 1.5, f"Line from {lab}.")
    return p["id"], cast.ensure_for_source(p["id"], {lab: talk for lab in voices})


def test_old_per_video_characters_become_work_characters_once(fresh):
    c = sqlite3.connect(fresh / "t.db")
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO projects (id,name,created) VALUES ('p','P',0)")
    c.execute("INSERT INTO characters (project_id,label,name,gender,important,color,talk_s) VALUES ('p','SPEAKER_00','Camille','f',1,3,60)")
    c.execute("INSERT INTO characters (project_id,label,name,important,color,talk_s) VALUES ('p','SPEAKER_01','Speaker 2',0,1,5)")
    c.execute("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES ('p',1,'SPEAKER_00',0,1,'Hi.')")
    c.commit()
    c.close()
    got = {s["label"]: s for s in cast.for_source("p")}
    assert (got["SPEAKER_00"]["name"], got["SPEAKER_00"]["gender"], got["SPEAKER_00"]["color"]) == ("Camille", "f", 3)
    assert got["SPEAKER_00"]["status"] == "confirmed" and not got["SPEAKER_00"]["auto"] and got["SPEAKER_00"]["talk_s"] == 60
    assert got["SPEAKER_01"]["important"] == 0 and got["SPEAKER_01"]["auto"]  # never touched by a person
    assert project.sentences("p")[0]["speaker"] == "SPEAKER_00"  # lines keep their label
    db._local.c = None
    db.conn()
    assert db.row("SELECT COUNT(*) n FROM cast")["n"] == 2  # once


def test_the_same_voice_in_another_episode_is_proposed_never_linked(fresh):
    s = series.create("6 Minute English", "course")
    e1, r1 = _episode(s["id"], "ep1", {"SPEAKER_00": NEIL, "SPEAKER_01": BETH})
    assert r1 == {"new": 2, "proposed": 0}
    names = {x["label"]: x for x in cast.for_source(e1)}
    cast.update(names["SPEAKER_00"]["uid"], name="Neil", gender="m")
    cast.update(names["SPEAKER_01"]["uid"], name="Beth", gender="f")
    # episode 2: the diarizer happens to number them the other way round, plus a guest
    e2, r2 = _episode(s["id"], "ep2", {"SPEAKER_00": BETH, "SPEAKER_01": NEIL, "SPEAKER_02": GUEST})
    assert r2 == {"new": 1, "proposed": 2}
    got = {x["label"]: x for x in cast.for_source(e2)}
    assert (got["SPEAKER_00"]["name"], got["SPEAKER_00"]["status"]) == ("Beth", "proposed")
    assert (got["SPEAKER_01"]["name"], got["SPEAKER_01"]["status"]) == ("Neil", "proposed")
    assert got["SPEAKER_01"]["score"] > 0.8 and got["SPEAKER_02"]["status"] == "confirmed" and got["SPEAKER_02"]["auto"]
    # a proposal is only a suggestion: it does not shape the character's voice yet
    assert cast.voiceprint(got["SPEAKER_01"]["uid"], exclude=None) is not None
    assert [a["source_id"] for a in db.rows("SELECT source_id FROM appearances WHERE character_uid=? AND status='confirmed'",
                                             got["SPEAKER_01"]["uid"])] == [e1]


def test_confirm_reject_link_and_merge(fresh):
    s = series.create("Show", "show")
    e1, _ = _episode(s["id"], "ep1", {"SPEAKER_00": NEIL, "SPEAKER_01": BETH})
    neil = {x["label"]: x for x in cast.for_source(e1)}["SPEAKER_00"]["uid"]
    cast.update(neil, name="Neil")
    e2, _ = _episode(s["id"], "ep2", {"SPEAKER_00": NEIL, "SPEAKER_01": GUEST})
    assert cast.confirm(e2, "SPEAKER_00")["status"] == "confirmed"
    assert cast.character_of(e2, "SPEAKER_00")["uid"] == neil
    assert len(cast.of_work(s["id"])[0]["appearances"]) == 2
    # a person edits the character once: it holds in both episodes
    cast.update(neil, gender="m")
    assert cast.character_of(e1, "SPEAKER_00")["gender"] == "m"
    # "not him": the voice becomes a character of its own; Neil keeps his other appearance
    cast.detach(e2, "SPEAKER_00")
    assert cast.character_of(e2, "SPEAKER_00")["uid"] != neil and cast.character_of(e1, "SPEAKER_00")["uid"] == neil
    # …and linked back by hand; the auto character made for it is removed again
    before = db.row("SELECT COUNT(*) n FROM cast")["n"]
    cast.link(e2, "SPEAKER_00", neil)
    assert db.row("SELECT COUNT(*) n FROM cast")["n"] == before - 1
    # two characters that are one person
    guest = cast.character_of(e2, "SPEAKER_01")["uid"]
    beth = cast.character_of(e1, "SPEAKER_01")["uid"]
    cast.set_name(beth, "am", "ቤዝ")
    merged = cast.merge(beth, guest)
    assert merged["names"] == {"am": "ቤዝ"} and cast.character_of(e1, "SPEAKER_01")["uid"] == guest
    with pytest.raises(ValueError):
        cast.merge(guest, guest)


def test_two_clusters_in_one_source_merge_their_lines(fresh):
    e, _ = _episode(None, "solo", {"SPEAKER_00": NEIL, "SPEAKER_01": BETH})
    cast.merge_labels(e, "SPEAKER_01", "SPEAKER_00")
    assert {s["speaker"] for s in project.sentences(e)} == {"SPEAKER_00"}
    assert [x["label"] for x in cast.for_source(e)] == ["SPEAKER_00"] and cast.for_source(e)[0]["talk_s"] == 60
    assert db.row("SELECT COUNT(*) n FROM cast")["n"] == 1  # the auto character left behind is gone


def test_a_standalone_video_joining_a_series_brings_its_cast(fresh):
    s = series.create("Show", "show")
    e1, _ = _episode(s["id"], "ep1", {"SPEAKER_00": NEIL})
    neil = cast.for_source(e1)[0]["uid"]
    cast.update(neil, name="Neil")
    solo, _ = _episode(None, "loose", {"SPEAKER_00": NEIL, "SPEAKER_01": GUEST})
    assert cast.for_source(solo)[0]["uid"] != neil  # a different work: strangers
    series.attach(solo, s["id"])
    got = {x["label"]: x for x in cast.for_source(solo)}
    assert (got["SPEAKER_00"]["uid"], got["SPEAKER_00"]["status"]) == (neil, "proposed")
    assert got["SPEAKER_01"]["status"] == "confirmed"
    assert {c["series_id"] for c in cast.of_work(s["id"])} == {s["id"]}
    # and back out: characters it shares with the series are copied, the series keeps Neil
    cast.confirm(solo, "SPEAKER_00")
    series.attach(solo, None)
    assert cast.character_of(solo, "SPEAKER_00")["uid"] != neil and cast.character_of(e1, "SPEAKER_00")["uid"] == neil
    assert cast.character_of(solo, "SPEAKER_00")["name"] == "Neil"
