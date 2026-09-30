"""The research runner, as a person uses it in a notebook: a folder in, results out,
and the app opens the results as they lie (models stood in for, see test_run)."""
import sys
from pathlib import Path

from app import db, mix, package, project, settings, tasks
from tests.test_run import _tone, stubs  # noqa: F401  (the fixture)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import research  # noqa: E402


def test_a_folder_is_dubbed_by_hand_and_the_app_opens_the_results(tmp_path, monkeypatch, stubs):  # noqa: F811
    monkeypatch.setattr(research, "_scratch", lambda: tmp_path / "scratch")
    videos = tmp_path / "drive" / "Teachings"
    videos.mkdir(parents=True)
    _tone(videos / "01 - Faith.mp4", 4, 440, video=True)
    _tone(videos / "02 - Grace.mp4", 4, 520, video=True)
    out = tmp_path / "drive" / "lb-output"
    saved = (db.DATA, db.DB_PATH, settings.PATH)
    res = research.run_folder(videos, out, "en", ["am"], dub_limit=1, hf_token="hf_test")
    assert res["videos"] == 2 and len(res["results"]) == 1
    assert list((out / "library").rglob("*.am.mp4")), "no dubbed MP4 in the output folder"
    # the app, later, on the owner's PC: open the results as they are
    monkeypatch.setattr(db, "DATA", tmp_path / "app")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app" / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    settings.PATH = saved[2]
    db._local.c = None
    rep = package.import_work(res["results"][0], fetch=False)  # no paths given: the package knows where its media are
    assert len(rep["sources"]["added"]) == 2
    dubbed = [p for p in rep["sources"]["added"] if (db.meta(p).get("exports") or {}).get("am")]
    assert len(dubbed) == 1
    p = dubbed[0]
    assert Path(db.meta(p)["exports"]["am"]["mp4"]).exists() and Path(project.get(p)["video"]).exists()
    assert mix.mix_dir(p, "am").is_relative_to(out / "library")
    db._local.c = None


def test_a_missing_separator_file_lets_audio_separator_try_its_other_repo(monkeypatch):
    """audio-separator 0.47 probes the UVR repo for a model's YAML and falls back to its
    own repo only on RuntimeError; a 404 must not stop the voice stage (Colab, 2026-09-26)."""
    import sys
    import types

    import requests

    from lb_worker import deps
    from lb_worker.stages import analysis

    Separator = type("Separator", (), {})
    fake = types.ModuleType("audio_separator.separator")
    fake.Separator = Separator
    monkeypatch.setitem(sys.modules, "audio_separator", types.ModuleType("audio_separator"))
    monkeypatch.setitem(sys.modules, "audio_separator.separator", fake)

    def not_there(url, dest, log=print, tries=5):
        raise requests.HTTPError(f"HTTP 404 for {url}")

    monkeypatch.setattr(deps, "fetch", not_there)
    analysis.patch_separator_download()
    for kind in (RuntimeError, requests.HTTPError):
        try:
            Separator().download_file_if_not_exists("https://x/model.yaml", "/tmp/model.yaml")
        except kind:
            pass
        else:
            raise AssertionError(f"no {kind.__name__}")


def test_a_newer_run_in_the_same_notebook_stops_the_older_ones_threads(tmp_path):
    from lb_worker import research

    old = research._current["ctx"] = research._Ctx(tmp_path, "a", tmp_path)
    assert not old.cancelled()
    research._current["ctx"] = research._Ctx(tmp_path, "b", tmp_path)
    assert old.cancelled()


def test_a_drive_run_shows_its_folder_state_and_its_new_results_come_in_by_themselves(tmp_path, monkeypatch):
    import json
    import os
    import time

    from app import runs

    monkeypatch.setattr(db, "DATA", tmp_path / "lib")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lib" / "t.db")
    db._local.c = None
    started = []
    monkeypatch.setattr(tasks, "start", lambda owner, kind, fn, *a, **k: started.append(a) or "t")
    d = Path(settings.root("colab")["path"]) / "runs" / "r1"
    (d / "results").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"stages": ["fetch", "voice"], "sources": ["a"], "created": 1}))
    (d / "state.json").write_text(json.dumps({"sources": {"a": {"fetch": "done"}}}))
    (d / "log.txt").write_text("18:30:01 voiced 57/439 (12%) · 3.1 s each · about 20 min left\n", encoding="utf-8")
    res = d / "results" / "w.lbwork"
    res.write_bytes(b"x")
    old = time.time() - 600
    os.utime(res, (old, old))
    db.run("INSERT INTO jobs (id,project_id,stage,created,role,root) VALUES (?,?,?,?,?,?)",
           "old-queue-job", "series:s", "pipeline", 1, "r1", "colab")

    r = runs.listing("series:s")[0]
    assert r["state"] == "running" and r["note"].startswith("voiced 57/439")  # the queue job is ignored
    assert started == [("colab", "r1")] and r["opening"]
    runs.listing("series:s")
    assert len(started) == 1  # already being brought in: not twice
    for p in (d / "state.json", d / "log.txt"):
        os.utime(p, (old - 3600, old - 3600))
    assert runs.status("colab", "r1", "old-queue-job")["state"] == "paused"


def test_a_run_folder_given_as_the_videos_continues_that_run(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text("{}")
    got = []
    monkeypatch.setattr(research, "run_manifest", lambda d, *a: got.append(d) or {"videos": 0})
    research.run_folder(str(tmp_path), tmp_path / "out")
    assert got == [str(tmp_path)]


def test_links_need_no_folder(tmp_path, monkeypatch):
    """Links alone make a run: a playlist expands into its videos (oldest first), a single
    video keeps its id and title, a .txt file stands for the links in it, duplicates go."""
    import json
    import subprocess

    listing = {"_type": "playlist", "title": "Talks", "entries": [
        {"id": "new1", "title": "Newest", "url": "https://example.org/v/new1"},
        {"id": "old1", "title": "Oldest", "url": "https://example.org/v/old1"}]}
    single = {"id": "abc", "title": "One talk", "webpage_url": "https://vimeo.com/abc"}

    def fake_run(cmd, **kw):
        if "yt_dlp" in cmd and "-J" in cmd:
            js = listing if "playlist" in cmd[-1] else single
            return subprocess.CompletedProcess(cmd, 0, json.dumps(js), "")
        raise AssertionError(cmd)

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    monkeypatch.setattr(research, "_scratch", lambda: tmp_path / "scratch")
    import lb_worker.deps as deps
    monkeypatch.setattr(deps, "ensure", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(research, "run_manifest", lambda d, *a, **k: seen.setdefault("dir", Path(d)) and {"videos": 0})
    txt = tmp_path / "links.txt"
    txt.write_text("# teachings\nhttps://vimeo.com/abc\n\nhttps://example.org/playlist?x=1\n", encoding="utf-8")
    assert research.read_links(f"{txt} https://vimeo.com/abc") == ["https://vimeo.com/abc", "https://example.org/playlist?x=1"]
    saved = (db.DATA, db.DB_PATH, settings.PATH)
    try:
        research.run_folder(None, tmp_path / "out", "en", ["am"], ["fetch"], links=[str(txt)])
        man = json.loads((seen["dir"] / "manifest.json").read_text(encoding="utf-8"))
        titles = [r["name"] for r in db.rows("SELECT name FROM projects ORDER BY position, created")]
    finally:
        db.DATA, db.DB_PATH, settings.PATH = saved
        db._local.c = None
    assert len(man["sources"]) == 3 and man["name"] == "Links"
    assert titles == ["One talk", "Oldest", "Newest"]
