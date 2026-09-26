import time

import numpy as np
import pytest
from scipy.io import wavfile

from app import db, library, recurring, series, tasks
from tests.test_fingerprint import SR, chords


@pytest.fixture()
def show(tmp_path, monkeypatch):
    """A three-episode series: every episode opens with the same 15 s intro after a
    cold open of a different length; episode 3's copy is quieter and noisy."""
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    s = series.create("Show", "show", targets=["am"])
    intro, rng = chords(1, 15), np.random.default_rng(3)
    eps = {"e1": (8, intro), "e2": (20, intro), "e3": (4, 0.8 * intro + 0.05 * rng.standard_normal(len(intro)))}
    ids = {}
    for k, (cold, x) in enumerate(eps.values()):
        name = list(eps)[k]
        audio = np.concatenate([chords(10 + k, cold), x, chords(20 + k, 30)])
        path = tmp_path / f"{name}.wav"
        wavfile.write(path, SR, (audio / np.abs(audio).max() * 20000).astype(np.int16))
        p = series.add_source(s["id"], name, str(path))
        db.run("UPDATE projects SET audio=?, duration=? WHERE id=?", str(path), len(audio) / SR, p["id"])
        ids[name] = p["id"]
    yield s["id"], ids
    db._local.c = None


def test_a_recurring_clip_is_found_in_the_other_episodes(show):
    sid, ids = show
    c = library.create_clip(ids["e1"], 8.0, 23.0, "Intro", "intro")
    occ = recurring.search(c["id"])
    got = {o["source_id"]: o["start"] for o in occ}
    assert set(got) == {ids["e2"], ids["e3"]}  # not its own place in episode 1
    assert abs(got[ids["e2"]] - 20.0) < 0.3 and abs(got[ids["e3"]] - 4.0) < 0.3
    assert all(o["status"] == "proposed" and abs(o["end"] - o["start"] - 15.0) < 0.01 for o in occ)


def test_a_persons_decision_survives_a_new_search(show):
    sid, ids = show
    c = library.create_clip(ids["e1"], 8.0, 23.0, "Intro", "intro")
    by = {o["source_id"]: o for o in recurring.search(c["id"])}
    recurring.set_status(by[ids["e2"]]["id"], "confirmed")
    recurring.set_status(by[ids["e3"]]["id"], "rejected")
    again = {o["source_id"]: o["status"] for o in recurring.search(c["id"])}
    assert again == {ids["e2"]: "confirmed", ids["e3"]: "rejected"}
    assert [o["source_id"] for o in recurring.confirmed_in(ids["e2"])] == [ids["e2"]]
    assert abs(recurring.confirmed_in(ids["e2"])[0]["offset"] - 12.0) < 0.3  # 20 s there, 8 s at the origin


def test_plain_clips_are_not_searched(show):
    sid, ids = show
    c = library.create_clip(ids["e1"], 8.0, 23.0, "A moment")
    with pytest.raises(ValueError):
        recurring.search(c["id"])


def test_discovery_proposes_the_shared_intro_until_it_is_cut(show):
    sid, ids = show
    cands = recurring.discover(sid)
    assert cands, "nothing discovered"
    top = cands[0]
    assert top["sources"] == 3 and top["of"] == 3 and top["kind"] == "intro"
    assert top["origin"]["source_id"] == ids["e1"] and abs(top["origin"]["start"] - 8.0) < 0.5
    assert abs(top["duration"] - 15.0) < 1.0
    c = library.create_clip(ids["e1"], top["origin"]["start"], top["origin"]["end"], "Intro", "intro")
    assert all(abs(x["origin"]["start"] - 8.0) > 1 for x in recurring.discover(sid))  # already cut: not proposed again
    assert recurring.confirm_all(c["id"]) == 0 and len(recurring.search(c["id"])) == 2
    assert recurring.confirm_all(c["id"]) == 2


def test_confirmed_parts_are_translated_and_voiced_once(show, monkeypatch):
    from app import project
    sid, ids = show
    e1, e2 = ids["e1"], ids["e2"]
    # the intro has a spoken line: 10–12 s in episode 1, so 22–24 s in episode 2 (intro at 20 s there)
    for pid, (a, b) in ((e1, (10.0, 12.0)), (e2, (22.1, 24.0))):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", pid, 1, "A", a, b, "Welcome to the show.")
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", pid, 2, "A", 40.0, 42.0, "Today: hope.")
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", pid, 3, "A", 34.5, 36.0, "Half in.")
    project.set_translation(e1, 1, "am", "ወደ ትርኢቱ እንኳን በደህና መጡ።")
    db.run("INSERT INTO takes (project_id,sentence_id,job_id,take,path,text,chosen,created,lang) VALUES (?,?,?,?,?,?,?,?,?)",
           e1, 1, "j1", 0, "take.wav", "ወደ ትርኢቱ እንኳን በደህና መጡ።", 1, time.time(), "am")
    c = library.create_clip(e1, 8.0, 23.0, "Intro", "intro")
    for o in recurring.search(c["id"]):
        if o["source_id"] == e2:
            recurring.set_status(o["id"], "confirmed")

    s2 = {s["id"]: s for s in project.sentences(e2, "am")}
    assert s2[1]["linked"]["source_id"] == e1 and s2[1]["linked"]["line_id"] == 1
    assert s2[1]["tr"] == "ወደ ትርኢቱ እንኳን በደህና መጡ።" and s2[1]["tr_provenance"] == "linked"
    assert s2[2]["linked"] is None and s2[3]["linked"] is None  # after the intro / only partly inside it
    assert all(s["linked"] is None for s in project.sentences(e1, "am"))  # the origin is not linked to itself
    assert project.summary(e2)["counts"]["linked"] == 1 and project.summary(e2)["counts"]["translated"] == 1

    batches = []

    class Fake:
        def __init__(self, *a, **k): pass

        def translate(self, items):
            batches.append([x["id"] for x in items])
            return {x["id"]: "t" for x in items}

    monkeypatch.setattr(project, "GoogleBatchTranslator", Fake)
    project._translate(e2, "am", None, False, lambda *a: None)
    assert batches == [[3, 2]]  # line 1 is not machine-translated here: it is the intro's

    takes = recurring.origin_takes(project.sentences(e2, "am"), "am")
    assert list(takes) == [1] and takes[1]["path"] == "take.wav"
