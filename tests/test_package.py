import json
import subprocess
import zipfile

import numpy as np
import pytest
from scipy.io import wavfile

from app import banks, cast, chapters, db, library, package, project, recurring, series, tasks


def _use(monkeypatch, root):
    monkeypatch.setattr(db, "DATA", root)
    monkeypatch.setattr(db, "DB_PATH", root / "langbridge.db")
    db._local.c = None


@pytest.fixture()
def team_a(tmp_path, monkeypatch):
    """Library A: a two-episode work with everything a team makes."""
    started = []
    monkeypatch.setattr(tasks, "start", lambda *a, **k: started.append(a[:2]) or "task")
    _use(monkeypatch, tmp_path / "a")
    s = series.create("Six Minutes", "course", "en", ["am"], feed_url="https://www.youtube.com/playlist?list=x")
    host = None
    for k in range(2):
        p = series.add_source(s["id"], f"Ep {k + 1}", f"https://youtu.be/ep{k}", 0, 60, origin_id=f"ep{k}")
        d = project.pdir(p["id"])
        t = np.arange(20 * 16000) / 16000
        wavfile.write(d / "v.wav", 16000, (np.sin(2 * np.pi * (220 + 40 * k) * t) * 8000).astype(np.int16))
        for name in ("clip", "vocals", "background"):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "v.wav"), str(d / f"{name}.flac")], check=True)
        db.run("UPDATE projects SET audio=?, duration=20 WHERE id=?", str(d / "clip.flac"), p["id"])
        for i, (a, b, txt) in enumerate([(1, 4, "Hello, this is Six Minutes."), (5, 9, "Today we talk about hope."),
                                         (10, 13, "Hope is a choice.")], 1):
            db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text,reviewed) VALUES (?,?,?,?,?,?,?)",
                   p["id"], i, "SPEAKER_00", a, b, txt, int(i == 1))
        (d / "diarization.json").write_text(json.dumps({"centroids": {"SPEAKER_00": [1.0] + [0.0] * 255}}))
        cast.ensure_for_source(p["id"], {"SPEAKER_00": 12.0})
        if k == 0:
            host = cast.for_source(p["id"])[0]["uid"]
            cast.update(host, name="Neil", gender="male", role="presenter")
            cast.set_name(host, "am", "ኒል")
        else:
            cast.confirm(p["id"], "SPEAKER_00")  # proposed by voice, confirmed by a person
        chapters.toggle(p["id"], 2)
        project.set_translation(p["id"], 1, "am", "ሰላም፣ ይህ ስድስት ደቂቃ ነው።", provenance="human")
        project.set_translation(p["id"], 2, "am", "ዛሬ ስለ ተስፋ እንነጋገራለን።", provenance="machine", locked=False)
    ids = [x["id"] for x in series.sources(s["id"])]
    banks.rebuild(host)
    intro = library.create_clip(ids[0], 1, 4, "Opening", "intro")
    db.run("INSERT INTO clip_occurrences (clip_id,source_id,start,end,score,status,updated) VALUES (?,?,1,4,0.5,'confirmed',0)",
           intro["id"], ids[1])
    faves = library.create_collection("Favourites")
    library.set_memberships("clip", intro["id"], [faves["id"]])
    take = project.pdir(ids[0]) / "takes" / "t.wav"
    take.parent.mkdir(exist_ok=True)
    wavfile.write(take, 16000, np.zeros(16000, dtype=np.int16))
    db.run("INSERT INTO takes (project_id,sentence_id,job_id,take,path,text,chosen,created,lang,dur_s) VALUES (?,1,'j',0,?,?,1,0,'am',1.0)",
           ids[0], str(take), "ሰላም፣ ይህ ስድስት ደቂቃ ነው።")
    db.run("INSERT INTO jobs (id,project_id,stage,created,role,root) VALUES ('job-1',?,'separate',0,'analysis','local')", ids[0])
    yield {"sid": s["id"], "ids": ids, "host": host, "uid": s["uid"], "tmp": tmp_path, "started": started, "mp": monkeypatch}
    db._local.c = None


def _snapshot():
    """Everything that should travel, keyed by uid (never by local ids or paths)."""
    src_uid = {r["id"]: r["uid"] for r in db.rows("SELECT id, uid FROM projects")}
    return {
        "work": db.rows("SELECT uid, name, kind, src_lang, feed_url FROM series WHERE kind<>'single'"),
        "sources": sorted((r["uid"], r["name"], r["origin_id"], r["clip_start"], r["clip_end"], r["position"])
                          for r in db.rows("SELECT * FROM projects")),
        "lines": sorted((src_uid[r["project_id"]], r["id"], r["text"], r["speaker"], r["reviewed"])
                        for r in db.rows("SELECT * FROM sentences")),
        "chapters": sorted((src_uid[r["project_id"]], r["id"], r["start"]) for r in db.rows("SELECT * FROM chapters")),
        "cast": sorted((r["uid"], r["name"], r["gender"], r["role"]) for r in db.rows("SELECT * FROM cast")),
        "names": sorted((r["character_uid"], r["lang"], r["name"]) for r in db.rows("SELECT * FROM cast_names")),
        "appearances": sorted((src_uid[r["source_id"]], r["label"], r["character_uid"], r["status"])
                              for r in db.rows("SELECT * FROM appearances")),
        "bank": sorted((r["character_uid"], src_uid[r["source_id"]], r["line_id"], r["role"]) for r in db.rows("SELECT * FROM cast_bank")),
        "clips": sorted((r["uid"], r["title"], r["kind"], src_uid[r["source_id"]]) for r in db.rows("SELECT * FROM clips")),
        "occurrences": sorted((src_uid[r["source_id"]], r["start"], r["status"]) for r in db.rows("SELECT * FROM clip_occurrences")),
        "collections": sorted(r["uid"] for r in db.rows("SELECT * FROM collections")),
        "translations": sorted((src_uid[r["project_id"]], r["sentence_id"], r["lang"], r["text"], r["provenance"])
                               for r in db.rows("SELECT * FROM translations")),
    }


def test_a_work_arrives_whole_in_another_library(team_a):
    a = team_a
    before = _snapshot()
    pkg = package.export(a["sid"], ["am"], media="flac", takes=True, note="for the Oromo team")
    with zipfile.ZipFile(pkg) as z:
        assert not any("jobs" in n or n.endswith(".db") for n in z.namelist())  # nothing local travels
        assert json.loads(z.read("work.json"))["work"]["uid"] == a["uid"]
    _use(a["mp"], a["tmp"] / "b")  # team B's library
    assert package.inspect(pkg)["here"] is None
    rep = package.import_work(pkg, fetch=False)
    assert rep["created"] and len(rep["sources"]["added"]) == 2 and rep["characters"]["added"] == 1
    after = _snapshot()
    for k in before:
        assert after[k] == before[k], k
    assert db.rows("SELECT * FROM jobs") == []
    assert all(str(a["tmp"] / "b") in r["path"] and __import__("os").path.exists(r["path"]) for r in db.rows("SELECT path FROM cast_bank"))
    pid = rep["sources"]["added"][0]
    assert (project.pdir(pid) / "vocals.flac").exists() and project.get(pid)["audio"].endswith("clip.flac")
    assert db.row("SELECT COUNT(*) n FROM takes WHERE lang='am' AND chosen=1")["n"] == 1
    assert cast.for_source(pid)[0]["name"] == "Neil" and cast.get(a["host"])["names"] == {"am": "ኒል"}
    assert recurring.confirmed_in(rep["sources"]["added"][1])  # the confirmed intro is confirmed here too
    # importing again changes nothing
    again = package.import_work(pkg, fetch=False)
    assert not again["created"] and again["sources"]["added"] == [] and _snapshot() == after


def test_people_here_are_never_overwritten(team_a):
    a = team_a
    pkg = package.export(a["sid"], ["am"], media="none")
    _use(a["mp"], a["tmp"] / "b")
    a["started"].clear()
    rep = package.import_work(pkg, fetch=True)
    # no media in the package: each source is fetched again from its origin (and nothing re-transcribed)
    assert sorted(rep["fetching"]) == sorted(rep["sources"]["added"])
    assert sorted(a["started"]) == sorted((pid, "import") for pid in rep["sources"]["added"])
    pid = rep["sources"]["added"][0]
    project.set_translation(pid, 2, "am", "የኛ ትርጉም።", provenance="human")  # team B rewrites a machine line
    cast.update(a["host"], name="Neil (host)")
    rep2 = package.import_work(pkg, fetch=False)
    assert project.sentences(pid, "am")[1]["tr"] == "የኛ ትርጉም።"
    assert rep2["translations"]["am"]["kept_here"] >= 1
    assert cast.get(a["host"])["name"] == "Neil (host)"


def test_a_newer_package_version_is_refused(team_a, tmp_path):
    bad = tmp_path / "x.lbwork"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("work.json", json.dumps({"format": package.FORMAT, "version": 99, "work": {"uid": "u"}}))
    with pytest.raises(ValueError):
        package.inspect(bad)
