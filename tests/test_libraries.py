import json
from pathlib import Path

import pytest

from app import db, libraries, project, settings, tasks

SRT = "1\n00:00:01,000 --> 00:00:03,000\nGrace to you.\n\n2\n00:00:03,500 --> 00:00:05,000\nAnd peace.\n"


def _touch(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def drive(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path / "app")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app" / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    yield Path(settings.root("colab")["path"]).parent  # the test's "G:/My Drive"
    db._local.c = None


def test_the_folder_standard(drive):
    lib = drive / "Team library"
    _touch(lib / "library.json", json.dumps({"language": "en", "targets": ["am", "om"]}))
    w = lib / "Faith Series"
    _touch(w / "work.json", json.dumps({"title": "The Faith Series", "kind": "speaker", "speakers": ["Pastor A"]}))
    for f in ("01 - Intro.mp4", "02 - Grace.mp4", "10 - End.mp4", "Season 2/01 - Again.mp4", "01 - Intro [hi].mp4"):
        _touch(w / f)
    _touch(w / "02 - Grace.srt", SRT)
    _touch(w / "02 - Grace.am.srt", SRT)
    _touch(lib / "_Standalone" / "Special Service.mp4")
    _touch(lib / "Welcome.mp4")
    _touch(lib / "Faith Series" / "desktop.ini")
    L = libraries.create("Team library", "colab", str(lib))
    assert libraries.scan(L["id"]) == {"works": 3, "new_works": 3, "videos": 7, "new_videos": 7}
    t = {x["name"]: x for x in libraries.tree(L["id"])}
    faith = t["The Faith Series"]
    assert faith["kind"] == "speaker" and faith["speakers"] == ["Pastor A"]
    assert [(v["name"], v["lang"], v["group"]) for v in faith["videos"]] == [
        ("01 - Intro", "en", None), ("01 - Intro", "hi", None), ("02 - Grace", "en", None), ("10 - End", "en", None),
        ("01 - Again", "en", "Season 2")]
    grace = next(v for v in faith["videos"] if v["name"] == "02 - Grace")
    assert grace["subtitles"] and grace["subtitles_other"] == ["am"]
    assert t["Special Service"]["standalone"] and t["Welcome"]["standalone"]
    p = project.get(grace["id"])
    assert p["source"] == "root:../Team library/Faith Series/02 - Grace.mp4" and Path(p["video"]).exists()
    assert project.targets(grace["id"]) == ["am", "om"]  # the library's languages
    assert db.meta(grace["id"])["refs"]["subtitles"] == "root:../Team library/Faith Series/02 - Grace.srt"
    # subtitles give lines at once; one speaker until a run finds them
    assert libraries.load_subtitles(L["id"]) == {"loaded": 1, "failed": []}
    assert [s["text"] for s in project.sentences(grace["id"])] == ["Grace to you.", "And peace."]
    # rescanning adds only what is new
    _touch(w / "11 - After.mp4")
    assert libraries.scan(L["id"])["new_videos"] == 1


def test_any_folder_tree_still_loads(drive, tmp_path):
    lib = drive / "Old uploads"
    _touch(lib / "3 Kinds of Knowledge" / "Volume 1" / "Part 2" / "3_Kinds_Part_2.mp3")
    _touch(lib / "3 Kinds of Knowledge" / "Volume 1" / "Part 10" / "3_Kinds_Part_10.mp3")
    _touch(lib / "5 Blessings" / "Hindi" / "x" / "5_Blessings_(Hindi).mp4")
    L = libraries.create("Old uploads", "colab", str(lib))
    libraries.scan(L["id"])
    t = {x["name"]: x for x in libraries.tree(L["id"])}
    assert [v["name"] for v in t["3 Kinds of Knowledge"]["videos"]] == ["3 Kinds Part 2", "3 Kinds Part 10"]
    assert t["5 Blessings"]["videos"][0]["lang"] == "hi"  # a folder named after a language
    ext = tmp_path / "E" / "Preachings"
    _touch(ext / "17 Gifts Of Demons" / "17 Gifts Of Demons Day 2 Video 1.mp4")
    L2 = libraries.create("Local disk", "local", str(ext))
    libraries.scan(L2["id"])
    v = libraries.tree(L2["id"])[0]["videos"][0]
    assert project.get(v["id"])["source"].startswith("file:")  # this PC's worker reads it by its full path


def test_a_colab_library_must_be_in_the_drive(drive, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(ValueError):
        libraries.create("Elsewhere", "colab", str(tmp_path / "elsewhere"))
