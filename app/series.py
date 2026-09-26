"""Series: families of sources that are worked on together.

A series is a show's episodes, a channel's videos, one speaker's talks, a course's
lessons or a news programme's segments. Its kind only changes wording and defaults;
every kind works the same way. A new source takes the series' source language,
target languages and settings, so a team sets them once.

Sources are ordinary projects with `series_id` and `position`; a project without a
series is a standalone video.
"""
from __future__ import annotations

import json
import re
import time

from . import cast, db, project

# kind → (what the series is called, what one source is called)
KINDS = {
    "show": ("Series", "episode"),
    "channel": ("Channel", "video"),
    "speaker": ("Speaker", "talk"),
    "course": ("Course", "lesson"),
    "news": ("News programme", "segment"),
    "other": ("Collection", "video"),
    "single": ("Video", "video"),  # a standalone video's own work: made by the app, never chosen
}
SETTINGS = ("max_speakers",)  # per-series defaults a new source takes


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "series"
    base, n = s, 2
    while db.row("SELECT id FROM series WHERE id=?", s):
        s, n = f"{base}-{n}", n + 1
    return s


def _check(kind: str | None, targets: list[str] | None) -> None:
    if kind is not None and (kind not in KINDS or kind == "single"):  # 'single' is made by the app, never chosen
        raise ValueError(f"kind must be one of {', '.join(k for k in KINDS if k != 'single')}")
    if targets is not None:
        if not targets:
            raise ValueError("a series needs at least one target language")
        for t in targets:
            project.check_lang(t)


def create(name: str, kind: str = "other", src_lang: str = "en", targets: list[str] | None = None,
           feed_url: str | None = None, settings: dict | None = None) -> dict:
    targets = [t.strip().lower() for t in (["am"] if targets is None else targets)]
    _check(kind, targets)
    project.check_lang(src_lang)
    sid = _slug(name)
    db.run("INSERT INTO series (id,name,kind,feed_url,src_lang,targets,settings,created,uid) VALUES (?,?,?,?,?,?,?,?,?)",
           sid, name.strip(), kind, (feed_url or "").strip() or None, src_lang, json.dumps(targets),
           json.dumps({k: v for k, v in (settings or {}).items() if k in SETTINGS}), time.time(), db.new_uid())
    return get(sid)


def get(sid: str) -> dict:
    s = db.row("SELECT * FROM series WHERE id=?", sid)
    if not s:
        raise KeyError(sid)
    s["targets"] = json.loads(s["targets"] or "[]")
    s["settings"] = json.loads(s["settings"] or "{}")
    s["label"], s["unit"] = KINDS.get(s["kind"], KINDS["other"])
    return s


def update(sid: str, **changes) -> dict:
    cur = get(sid)
    _check(changes.get("kind"), changes.get("targets"))
    if "src_lang" in changes:
        project.check_lang(changes["src_lang"])
    row = {k: changes.get(k, cur[k]) for k in ("name", "kind", "feed_url", "src_lang", "targets", "settings")}
    row["settings"] = {k: v for k, v in (row["settings"] or {}).items() if k in SETTINGS}
    db.run("UPDATE series SET name=?, kind=?, feed_url=?, src_lang=?, targets=?, settings=? WHERE id=?",
           row["name"].strip(), row["kind"], (row["feed_url"] or "").strip() or None, row["src_lang"],
           json.dumps(row["targets"]), json.dumps(row["settings"]), sid)
    return get(sid)


def sources(sid: str) -> list[dict]:
    """The series' sources in their order, as project summaries."""
    return [project.summary(r["id"]) for r in
            db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created", sid)]


def listing() -> list[dict]:
    """The series people made (not the hidden single-source works of standalone videos)."""
    out = []
    for r in db.rows("SELECT id FROM series WHERE kind<>'single' ORDER BY created DESC"):
        s = get(r["id"])
        srcs = db.rows("SELECT id, duration FROM projects WHERE series_id=?", s["id"])
        s["counts"] = {"sources": len(srcs), "duration": sum(x["duration"] or 0 for x in srcs)}
        out.append(s)
    return out


def _next_position(sid: str) -> float:
    return (db.row("SELECT MAX(position) m FROM projects WHERE series_id=?", sid)["m"] or 0) + 1


def add_source(sid: str, name: str, source: str, clip_start: float | None = None, clip_end: float | None = None,
               max_speakers: int | None = None, origin_id: str | None = None, published: str | None = None,
               defer: bool = False) -> dict:
    """Create a source in this series, with the series' languages and settings, and
    start its import (download, audio, analysis) like any project — or, ``defer``,
    only register it for a remote worker to fetch (app/bulk.py)."""
    s = get(sid)
    if origin_id and db.row("SELECT id FROM projects WHERE series_id=? AND origin_id=?", sid, origin_id):
        raise ValueError("this video is already in the series")
    ms = max_speakers if max_speakers is not None else s["settings"].get("max_speakers")
    p = project.create(name, source, clip_start, clip_end, ms, s["src_lang"], s["targets"][0],
                       extra_targets=s["targets"][1:],
                       series=dict(series_id=sid, position=_next_position(sid), origin_id=origin_id, published=published),
                       defer=defer)
    return project.summary(p["id"])


def _drop_if_empty_single(sid: str | None) -> None:
    w = db.row("SELECT kind FROM series WHERE id=?", sid) if sid else None
    if w and w["kind"] == "single" and not db.row("SELECT 1 FROM projects WHERE series_id=?", sid):
        db.run("DELETE FROM series WHERE id=?", sid)


def attach(pid: str, sid: str | None) -> dict:
    """Move an existing project into a series (at the end), or back out to standalone
    (its own single-source work). Its clips move with it. Its languages stay its own;
    the series' targets are added to it."""
    old = project.get(pid)["series_id"]
    if sid is None:
        if not project.summary(pid)["standalone"]:
            cast.move_source(pid, old, project.single_work(pid))
        return project.summary(pid)
    s = get(sid)
    db.run("UPDATE projects SET series_id=?, position=? WHERE id=?", sid, _next_position(sid), pid)
    db.run("UPDATE clips SET series_id=? WHERE source_id=?", sid, pid)
    if old != sid:
        cast.move_source(pid, old, sid)  # its characters come along (and may match the series' cast)
        _drop_if_empty_single(old)
    for t in s["targets"]:
        project.add_target(pid, t)
    return project.summary(pid)


def remove(sid: str) -> int:
    """Remove the series itself. Its sources are kept and become standalone videos.
    Returns how many sources were released."""
    get(sid)
    ids = [r["id"] for r in db.rows("SELECT id FROM projects WHERE series_id=?", sid)]
    for pid in ids:
        attach(pid, None)
    db.run("DELETE FROM series WHERE id=?", sid)
    return len(ids)


def reorder(sid: str, ids: list[str]) -> list[dict]:
    """Set the sources' order; ids not listed keep their relative order after the listed ones."""
    get(sid)
    rest = [r["id"] for r in db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created", sid)
            if r["id"] not in ids]
    for i, pid in enumerate([*ids, *rest], 1):
        db.run("UPDATE projects SET position=? WHERE id=? AND series_id=?", float(i), pid, sid)
    return sources(sid)
