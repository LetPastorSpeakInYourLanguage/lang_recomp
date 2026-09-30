"""The team's working folder and its lang-bridge.json (lb_core/workspace/config.py), and a
run on it: the folder's videos and its recorded links, results in .lb/."""
import json
import sys
from pathlib import Path

import pytest

from app import db, settings
from lb_core.workspace import config as wsc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import research  # noqa: E402


def test_a_new_folder_gets_a_config(tmp_path):
    cfg, warn = wsc.open_workspace(tmp_path / "Preaching", "en", ["am"], ["https://y/1"])
    assert warn == [] and cfg["language"] == "en" and cfg["targets"] == ["am"] and cfg["links"] == ["https://y/1"]
    on_disk = wsc.load(tmp_path / "Preaching")
    assert on_disk["uid"] == cfg["uid"] and on_disk["name"] == "Preaching"
    with pytest.raises(wsc.WorkspaceError, match="LANGUAGE"):
        wsc.open_workspace(tmp_path / "Empty", None)


def test_settings_and_folder_disagree(tmp_path):
    wsc.open_workspace(tmp_path, "en", ["am"], ["https://y/1"])
    with pytest.raises(wsc.WorkspaceError, match="'tr'.*'en'"):
        wsc.open_workspace(tmp_path, "tr", ["am"])  # a different language: stop, with the fix
    cfg, warn = wsc.open_workspace(tmp_path, "en", ["om"], ["https://y/2", "https://y/1"])
    assert cfg["targets"] == ["am", "om"]  # both are done this run …
    assert wsc.load(tmp_path)["targets"] == ["am"]  # … the folder keeps its own list
    assert wsc.load(tmp_path)["links"] == ["https://y/1", "https://y/2"]  # links are sources: recorded
    assert any("om" in w for w in warn) and any("new link" in w for w in warn)
    cfg, warn = wsc.open_workspace(tmp_path)  # no settings: the folder's
    assert cfg["language"] == "en" and warn == []


def test_a_workspace_run_takes_its_videos_and_its_recorded_links(tmp_path, monkeypatch):
    ws = tmp_path / "Team"
    (ws / "Faith").mkdir(parents=True)
    (ws / "Faith" / "01 - Talk.mp4").write_bytes(b"x")
    (ws / ".lb" / "library" / "old").mkdir(parents=True)
    (ws / ".lb" / "library" / "old" / "video.mp4").write_bytes(b"x")  # made by an earlier run: not a source
    wsc.open_workspace(ws, "en", ["am"], ["https://y/old"])
    seen = {}
    monkeypatch.setattr(research, "run_folder", lambda videos, out, lang, targets, stages, **kw:
                        seen.update(videos=videos, out=out, lang=lang, targets=targets, **kw) or {"videos": 0})
    research.run_workspace(ws, "en", ["om"], "https://y/new", ["fetch"])
    assert seen["videos"] == ws and seen["out"] == ws / ".lb" and seen["targets"] == ["am", "om"]
    assert seen["links"] == ["https://y/old", "https://y/new"] and seen["name"] == "Team"
    only_made = tmp_path / "Only made"
    (only_made / ".lb").mkdir(parents=True)
    (only_made / ".lb" / "video.mp4").write_bytes(b"x")
    assert research._has_videos(ws) and not research._has_videos(only_made)  # .lb is never searched


def test_links_only_workspace_starts_empty(tmp_path, monkeypatch):
    ws = tmp_path / "Links team"
    seen = {}
    monkeypatch.setattr(research, "run_folder", lambda videos, out, *a, **kw: seen.update(videos=videos, out=out, **kw))
    with pytest.raises(SystemExit, match="no videos and no links"):
        research.run_workspace(ws, "en", ["am"])
    research.run_workspace(ws, "en", ["am"], "https://y/1 https://y/2")
    assert seen["videos"] is None and seen["out"] == ws / ".lb"
    assert json.loads((ws / "lang-bridge.json").read_text(encoding="utf-8"))["links"] == ["https://y/1", "https://y/2"]


def test_the_app_finds_a_workspace_runs_in_lb(tmp_path):
    from app import runs

    s = settings.load()
    s["roots"] = s["roots"] + [{"id": "team", "name": "Team", "kind": "folder", "path": str(tmp_path)}]
    settings.save(s)
    assert runs._root("team") == tmp_path  # an old output folder
    (tmp_path / ".lb").mkdir()
    assert runs._root("team") == tmp_path / ".lb"
