"""Chapters: a project's lines grouped into named, time-bounded parts.

A chapter has a stable id and a start time; it runs until the next chapter starts
(the last one to the end of the clip). A line belongs to the chapter containing
its start, so merges, splits and re-analysis never rewrite membership. The first
chapter always opens the clip at 0 and cannot be removed.

Chapters are the unit of translation context today, and of assignment, recording
sessions and journey moments later (see docs/PLAN.md).
"""
from __future__ import annotations

import bisect
import time

from . import db

EPS = 1e-3  # seconds; line starts closer than this are the same instant


def _rows(pid: str) -> list[dict]:
    return db.rows("SELECT * FROM chapters WHERE project_id=? ORDER BY start, id", pid)


def ensure(pid: str) -> list[dict]:
    """The project's chapters in time order; creates the opening chapter if none."""
    chs = _rows(pid)
    if not chs:
        db.run("INSERT INTO chapters (project_id,id,start,title,updated) VALUES (?,1,0,'',?)", pid, time.time())
        chs = _rows(pid)
    return chs


def assign(sents: list[dict], chs: list[dict]) -> None:
    """Set ``chapter`` (id) and ``chapter_head`` (first line of a later chapter) on each line."""
    starts = [c["start"] for c in chs]
    seen: set[int] = set()
    for s in sorted(sents, key=lambda x: x["start"]):
        c = chs[max(0, bisect.bisect_right(starts, s["start"] + EPS) - 1)]
        s["chapter"] = c["id"]
        s["chapter_head"] = int(c["id"] not in seen and c is not chs[0])
        seen.add(c["id"])


def listing(pid: str) -> list[dict]:
    """Chapters with their index, end time and line count."""
    chs = ensure(pid)
    sents = db.rows("SELECT id, start, end FROM sentences WHERE project_id=?", pid)
    assign(sents, chs)
    p = db.row("SELECT duration FROM projects WHERE id=?", pid) or {}
    clip_end = p.get("duration") or max([s["end"] for s in sents] + [0.0])
    for i, c in enumerate(chs):
        c["index"] = i
        c["end"] = chs[i + 1]["start"] if i + 1 < len(chs) else clip_end
        c["lines"] = sum(1 for s in sents if s["chapter"] == c["id"])
    return chs


def toggle(pid: str, sid: int) -> dict:
    """The transcript's C key: start a chapter at this line, or, if the line already
    starts one, fold that chapter back into the one before it."""
    chs = ensure(pid)
    sents = db.rows("SELECT id, start FROM sentences WHERE project_id=?", pid)
    assign(sents, chs)
    s = next((x for x in sents if x["id"] == sid), None)
    if s is None:
        raise ValueError("no such line")
    mine = [x for x in sents if x["chapter"] == s["chapter"]]
    if min(x["start"] for x in mine) >= s["start"] - EPS:  # s opens its chapter
        if s["chapter"] == chs[0]["id"]:
            raise ValueError("the first line always opens the first chapter")
        db.run("DELETE FROM chapters WHERE project_id=? AND id=?", pid, s["chapter"])
        return {"removed": s["chapter"]}
    new_id = max(c["id"] for c in chs) + 1
    db.run("INSERT INTO chapters (project_id,id,start,title,updated) VALUES (?,?,?,'',?)",
           pid, new_id, s["start"], time.time())
    return {"added": new_id}


def rename(pid: str, cid: int, title: str) -> None:
    if not db.row("SELECT 1 FROM chapters WHERE project_id=? AND id=?", pid, cid):
        raise ValueError("no such chapter")
    db.run("UPDATE chapters SET title=?, updated=? WHERE project_id=? AND id=?", title.strip(), time.time(), pid, cid)


def normalize(pid: str) -> None:
    """After lines change (merge, split, reload): a chapter that no longer holds a
    line is dropped (the boundary was merged away), and every later chapter starts
    exactly at its first line."""
    chs = ensure(pid)
    sents = db.rows("SELECT id, start FROM sentences WHERE project_id=?", pid)
    if not sents:
        return
    assign(sents, chs)
    first: dict[int, float] = {}
    for s in sents:
        first[s["chapter"]] = min(first.get(s["chapter"], s["start"]), s["start"])
    for c in chs[1:]:
        if c["id"] not in first:
            db.run("DELETE FROM chapters WHERE project_id=? AND id=?", pid, c["id"])
        elif abs(first[c["id"]] - c["start"]) > EPS:
            db.run("UPDATE chapters SET start=? WHERE project_id=? AND id=?", first[c["id"]], pid, c["id"])


def group(sents: list[dict], chs: list[dict]) -> list[tuple[dict, list[dict]]]:
    """(chapter, its lines in time order) for chapters that hold lines."""
    assign(sents, chs)
    by: dict[int, list[dict]] = {}
    for s in sorted(sents, key=lambda x: x["start"]):
        by.setdefault(s["chapter"], []).append(s)
    return [(c, by[c["id"]]) for c in chs if c["id"] in by]
