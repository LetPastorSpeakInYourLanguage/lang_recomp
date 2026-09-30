"""A team's working folder (the workspace) and its config, ``lang-bridge.json``.

Every run works in a workspace, even one whose videos all come from links: the folder
holds the config (language, target languages, every link ever added), the team's own
videos in any nesting, and everything made from them under ``.lb/`` (docs/WORKSPACE_PLAN.md).
Links are sources of the workspace just like its files: they are recorded here, so the
next run, another notebook or the app sees them without anyone copying media.

When a notebook's settings and the folder disagree (decision 38): a different source
language is an error; target languages and links are a union (both are done), with a
warning so the person running the notebook knows.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

FILE = "lang-bridge.json"
DATA = ".lb"  # everything the pipeline makes, inside the workspace
FORMAT, VERSION = "lang-bridge.workspace", 1


class WorkspaceError(ValueError):
    """The settings and the workspace cannot both be right: the person must choose."""


def path(workspace: str | Path) -> Path:
    return Path(workspace) / FILE


def load(workspace: str | Path) -> dict | None:
    """The config, or None when the folder has none yet (or it is half-synced)."""
    try:
        cfg = json.loads(path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("format") == FORMAT else None


def save(workspace: str | Path, cfg: dict) -> None:
    """Written whole and swapped in, so a reader (or Drive) never sees half a file."""
    p = path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))


def open_workspace(workspace: str | Path, language: str | None = None, targets: list[str] | None = None,
                   links: list[str] | None = None, name: str | None = None) -> tuple[dict, list[str]]:
    """The workspace as this run should see it, and warnings for the person.

    A folder without a config gets one from the settings. Links given now that the folder
    does not know yet are added to it (sources belong to the workspace). Returns the config
    with ``targets`` = the folder's plus the settings' (this run does both)."""
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    language = (language or "").strip().lower() or None
    targets = _uniq(t.lower() for t in targets or [])
    links = _uniq(links or [])
    cfg, warnings = load(ws), []
    if cfg is None:
        if not language:
            raise WorkspaceError(f"{ws} is a new workspace: set LANGUAGE (the videos' language, e.g. en).")
        cfg = {"format": FORMAT, "version": VERSION, "uid": str(uuid.uuid4()), "name": name or ws.name or "workspace",
               "language": language, "targets": targets or ["am"], "links": links, "created": time.time()}
        save(ws, cfg)
        return cfg, warnings
    if language and language != cfg.get("language"):
        raise WorkspaceError(f"LANGUAGE is {language!r} but the workspace {ws} is in {cfg.get('language')!r}: "
                             f"set LANGUAGE = {cfg.get('language')!r}, or use another folder for videos in {language!r}.")
    have = _uniq(cfg.get("targets") or [])
    extra = [t for t in targets if t not in have]
    if extra:
        warnings.append(f"TARGETS adds {', '.join(extra)} to the workspace's {', '.join(have) or 'none'}: "
                        "this run dubs into both (the workspace keeps its own list; change it in the app).")
    new_links = [l for l in links if l not in (cfg.get("links") or [])]
    if new_links:
        cfg["links"] = _uniq([*(cfg.get("links") or []), *new_links])
        cfg["updated"] = time.time()
        save(ws, cfg)
        warnings.append(f"{len(new_links)} new link(s) recorded in the workspace ({len(cfg['links'])} in all).")
    return cfg | {"targets": _uniq([*have, *extra])}, warnings
