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
