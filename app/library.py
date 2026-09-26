"""The team library: clips and the collections that hold them.

A **clip** is a saved span of one source, snapped to whole lines: a moment worth
keeping (for recomposition, or just because it is good), or a **recurring part** — an
intro, opener, outro, jingle or sign-off that repeats across a series and is dubbed
once (occurrences: app/fingerprint.py). Its spans are stored as revisions in
recomposer's cut_revision shape, ``[{source_id, start, end}]``, so a journey can later
pin the revision it used. Editing the span adds a revision; title, kind and note are
edited in place.

A **collection** is a flat folder; an item can be in several. Collections hold clips
now and stage presets once journeys exist (Phase D). Archiving a collection never
touches its items; removing a clip is a soft delete that can be undone.
"""
from __future__ import annotations

import json
import time

from . import chapters, db

KINDS = ("clip", "intro", "opener", "outro", "jingle", "recurring")
RECURRING = set(KINDS) - {"clip"}
ITEM_TYPES = ("clip", "stage_preset")


def _source(pid: str) -> dict:
    p = db.row("SELECT id, series_id FROM projects WHERE id=?", pid)
    if not p:
        raise ValueError("no such source")
    return p


def span_of_lines(pid: str, first_id: int, last_id: int) -> tuple[float, float]:
    """The span from one line's start to another's end (either order)."""
    rows = {r["id"]: r for r in db.rows("SELECT id, start, end FROM sentences WHERE project_id=? AND id IN (?,?)",
                                        pid, first_id, last_id)}
    if first_id not in rows or last_id not in rows:
        raise ValueError("no such line")
    a, b = rows[first_id], rows[last_id]
    return min(a["start"], b["start"]), max(a["end"], b["end"])


def _check(kind: str | None, title: str | None) -> None:
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if title is not None and not title.strip():
        raise ValueError("a clip needs a title")


def create_clip(pid: str, start: float, end: float, title: str, kind: str = "clip", note: str = "") -> dict:
    _check(kind, title)
    if end <= start:
        raise ValueError("a clip must end after it starts")
    p = _source(pid)
    now = time.time()
    c = db.conn()
    cur = c.execute("INSERT INTO clips (series_id,source_id,title,kind,note,created,updated,uid) VALUES (?,?,?,?,?,?,?,?)",
                    (p["series_id"], pid, title.strip()[:120], kind, note, now, now, db.new_uid()))
    cid = cur.lastrowid
    c.execute("INSERT INTO clip_revisions (clip_id,rev,segments,created) VALUES (?,1,?,?)",
              (cid, json.dumps([{"source_id": pid, "start": round(start, 3), "end": round(end, 3)}]), now))
    c.commit()
    return get_clip(cid)


def revise_clip(cid: int, segments: list[dict]) -> dict:
    """A new revision of the clip's spans; earlier revisions stay readable."""
    get_clip(cid)
    if not segments or any(s["end"] <= s["start"] for s in segments):
        raise ValueError("every span must end after it starts")
    for s in segments:
        _source(s["source_id"])
    rev = db.row("SELECT MAX(rev) r FROM clip_revisions WHERE clip_id=?", cid)["r"] + 1
    db.run("INSERT INTO clip_revisions (clip_id,rev,segments,created) VALUES (?,?,?,?)", cid, rev,
           json.dumps([{"source_id": s["source_id"], "start": round(s["start"], 3), "end": round(s["end"], 3)}
                       for s in segments]), time.time())
    db.run("UPDATE clips SET updated=? WHERE id=?", time.time(), cid)
    return get_clip(cid)


def update_clip(cid: int, title: str | None = None, kind: str | None = None, note: str | None = None) -> dict:
    c = get_clip(cid)
    _check(kind, title)
    db.run("UPDATE clips SET title=?, kind=?, note=?, updated=? WHERE id=?",
           (title.strip()[:120] if title is not None else c["title"]), kind or c["kind"],
           note if note is not None else c["note"], time.time(), cid)
    return get_clip(cid)


def remove_clip(cid: int, restore: bool = False) -> dict:
    get_clip(cid)
    db.run("UPDATE clips SET deleted=?, updated=? WHERE id=?", 0 if restore else 1, time.time(), cid)
    return get_clip(cid)


def get_clip(cid: int, rev: int | None = None) -> dict:
    c = db.row("SELECT * FROM clips WHERE id=?", cid)
    if not c:
        raise KeyError(cid)
    r = db.row("SELECT * FROM clip_revisions WHERE clip_id=? AND rev=?", cid, rev) if rev else \
        db.row("SELECT * FROM clip_revisions WHERE clip_id=? ORDER BY rev DESC LIMIT 1", cid)
    if not r:
        raise KeyError(f"{cid}#{rev}")
    c["rev"], c["segments"] = r["rev"], json.loads(r["segments"])
    c["duration"] = round(sum(s["end"] - s["start"] for s in c["segments"]), 3)
    c["recurring"] = c["kind"] in RECURRING
    c["collections"] = [x["collection_id"] for x in db.rows(
        "SELECT collection_id FROM collection_items WHERE item_type='clip' AND item_id=? ORDER BY collection_id", cid)]
    return c


def clip_lines(c: dict, lang: str | None = None) -> list[dict]:
    """The lines inside the clip's spans (text, speaker and, with ``lang``, the translation)."""
    out = []
    for s in c["segments"]:
        rows = db.rows("SELECT s.id, s.start, s.end, s.speaker, s.text, t.text AS tr FROM sentences s"
                       " LEFT JOIN translations t ON t.project_id=s.project_id AND t.sentence_id=s.id AND t.lang=?"
                       " WHERE s.project_id=? AND s.start >= ? - 0.01 AND s.end <= ? + 0.01 ORDER BY s.start",
                       lang or "", s["source_id"], s["start"], s["end"])
        out += [r | {"source_id": s["source_id"], "tr": r["tr"] or ""} for r in rows]
    return out


def clips(series_id: str | None = None, source_id: str | None = None, collection: int | None = None,
          kind: str | None = None, deleted: bool = False, lang: str | None = None) -> list[dict]:
    sql, args = "SELECT id FROM clips WHERE deleted=?", [int(deleted)]
    if series_id is not None:
        sql, args = sql + " AND series_id=?", [*args, series_id]
    if source_id is not None:
        sql, args = sql + " AND source_id=?", [*args, source_id]
    if kind is not None:
        sql, args = sql + " AND kind=?", [*args, kind]
    if collection is not None:
        sql += " AND id IN (SELECT item_id FROM collection_items WHERE item_type='clip' AND collection_id=?)"
        args.append(collection)
    out = []
    for r in db.rows(sql + " ORDER BY created DESC", *args):
        c = get_clip(r["id"])
        c["lines"] = clip_lines(c, lang)
        out.append(c)
    return out


# ---- collections --------------------------------------------------------------------------
def _name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("a collection needs a name")
    return name[:80]


def create_collection(name: str) -> dict:
    c = db.conn()
    cid = c.execute("INSERT INTO collections (name,created,uid) VALUES (?,?,?)",
                    (_name(name), time.time(), db.new_uid())).lastrowid
    c.commit()
    return get_collection(cid)


def get_collection(cid: int) -> dict:
    c = db.row("SELECT * FROM collections WHERE id=?", cid)
    if not c:
        raise KeyError(cid)
    c["items"] = db.row("SELECT COUNT(*) n FROM collection_items i LEFT JOIN clips k ON i.item_type='clip' AND k.id=i.item_id"
                        " WHERE i.collection_id=? AND COALESCE(k.deleted,0)=0", cid)["n"]
    return c


def collections(deleted: bool = False) -> list[dict]:
    return [get_collection(r["id"]) for r in db.rows("SELECT id FROM collections WHERE deleted=? ORDER BY name", int(deleted))]


def rename_collection(cid: int, name: str) -> dict:
    get_collection(cid)
    db.run("UPDATE collections SET name=? WHERE id=?", _name(name), cid)
    return get_collection(cid)


def archive_collection(cid: int, restore: bool = False) -> dict:
    """Archive (or restore) the folder. Its items are never deleted, and keep their
    other memberships."""
    get_collection(cid)
    db.run("UPDATE collections SET deleted=? WHERE id=?", 0 if restore else 1, cid)
    return get_collection(cid)


def set_memberships(item_type: str, item_id: int, collection_ids: list[int]) -> list[int]:
    """Replace the set of collections an item is in (recomposer's membership write)."""
    if item_type not in ITEM_TYPES:
        raise ValueError(f"item_type must be one of {', '.join(ITEM_TYPES)}")
    if item_type == "clip":
        get_clip(item_id)
    want = set(collection_ids)
    for cid in want:
        get_collection(cid)
    have = {r["collection_id"] for r in db.rows(
        "SELECT collection_id FROM collection_items WHERE item_type=? AND item_id=?", item_type, item_id)}
    for cid in have - want:
        db.run("DELETE FROM collection_items WHERE collection_id=? AND item_type=? AND item_id=?", cid, item_type, item_id)
    for cid in want - have:
        db.run("INSERT INTO collection_items (collection_id,item_type,item_id,added) VALUES (?,?,?,?)",
               cid, item_type, item_id, time.time())
    return sorted(want)


def chapter_span(pid: str, chapter_id: int) -> tuple[float, float]:
    """A whole chapter as a clip span (its first line's start to its last line's end)."""
    for c, lines in chapters.group(db.rows("SELECT id, start, end FROM sentences WHERE project_id=?", pid),
                                   chapters.ensure(pid)):
        if c["id"] == chapter_id:
            return lines[0]["start"], lines[-1]["end"]
    raise ValueError("no such chapter, or it has no lines")
