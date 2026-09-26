"""Recurring parts: where an intro, opener, outro, jingle or sign-off occurs.

A recurring clip (app/library.py) is cut once, from its origin source. ``search``
looks for it in every source of its series (and elsewhere in its own source) by
audio fingerprint and records each hit as a *proposed* occurrence. Only a person
confirms or rejects one, and a later search never changes that decision. Confirmed
occurrences are what dubbing reuses (lines inside them are linked to the origin).

``discover`` finds candidates nobody has cut yet: long stretches of sound that
sources of a series share. It stores nothing; saving a candidate makes a clip, and
its occurrences are then searched like any other.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import db, fingerprint as fp, library, project

STATUSES = ("proposed", "confirmed", "rejected")
SAME_PLACE_S = 1.0  # two hits closer than this are the same occurrence


def source_print(pid: str):
    """The source's fingerprint (cached next to its audio), or None without audio."""
    audio = project.pdir(pid) / "clip.flac"
    p = db.row("SELECT audio FROM projects WHERE id=?", pid)
    if p and p["audio"] and Path(p["audio"]).exists():
        audio = Path(p["audio"])
    if not audio.exists():
        return None
    return fp.cached(audio, project.pdir(pid) / "fingerprint.npy")


def _siblings(c: dict) -> list[str]:
    """Sources to search: the clip's series, or only its own source when standalone."""
    if c["series_id"]:
        return [r["id"] for r in db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created",
                                         c["series_id"])]
    return [c["source_id"]]


def search(cid: int) -> list[dict]:
    """Look for a recurring clip everywhere it could occur; new hits become proposed."""
    c = library.get_clip(cid)
    if not c["recurring"]:
        raise ValueError("only recurring parts (intro, opener, outro, jingle, recurring) are searched for")
    seg = c["segments"][0]
    origin = source_print(seg["source_id"])
    if origin is None:
        raise ValueError("the clip's source has no audio yet")
    first, part = fp.part_frames(origin, seg["start"], seg["end"])
    dur = seg["end"] - seg["start"]
    for pid in _siblings(c):
        src = origin if pid == seg["source_id"] else source_print(pid)
        if src is None:
            continue
        skip = (first, first + len(part)) if pid == seg["source_id"] else None
        for frame, score in fp.find_part(part, src, skip=skip):
            _propose(cid, pid, fp.to_seconds(frame), dur, score)
    return occurrences(cid)


def _propose(cid: int, pid: str, start: float, dur: float, score: float) -> None:
    near = db.row("SELECT * FROM clip_occurrences WHERE clip_id=? AND source_id=? AND ABS(start-?) < ?",
                  cid, pid, start, SAME_PLACE_S)
    if near:  # already known: refresh the measurement, never the person's decision
        if near["status"] == "proposed":
            db.run("UPDATE clip_occurrences SET start=?, end=?, score=?, updated=? WHERE id=?",
                   start, round(start + dur, 3), score, time.time(), near["id"])
        return
    db.run("INSERT INTO clip_occurrences (clip_id,source_id,start,end,score,status,updated) VALUES (?,?,?,?,?,?,?)",
           cid, pid, start, round(start + dur, 3), score, "proposed", time.time())


def occurrences(cid: int, status: str | None = None) -> list[dict]:
    sql = ("SELECT o.*, p.name AS source_name, p.position FROM clip_occurrences o LEFT JOIN projects p ON p.id=o.source_id"
           " WHERE o.clip_id=?")
    args: list = [cid]
    if status:
        sql, args = sql + " AND o.status=?", [*args, status]
    return db.rows(sql + " ORDER BY p.position, p.created, o.start", *args)


def set_status(oid: int, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if not db.row("SELECT 1 FROM clip_occurrences WHERE id=?", oid):
        raise KeyError(oid)
    db.run("UPDATE clip_occurrences SET status=?, updated=? WHERE id=?", status, time.time(), oid)
    return db.row("SELECT * FROM clip_occurrences WHERE id=?", oid)


def confirm_all(cid: int) -> int:
    n = len(occurrences(cid, "proposed"))
    db.run("UPDATE clip_occurrences SET status='confirmed', updated=? WHERE clip_id=? AND status='proposed'",
           time.time(), cid)
    return n


def confirmed_in(pid: str) -> list[dict]:
    """Confirmed occurrences in a source, with their clip's origin span: what dubbing reuses."""
    out = []
    for o in db.rows("SELECT o.* FROM clip_occurrences o JOIN clips c ON c.id=o.clip_id"
                     " WHERE o.source_id=? AND o.status='confirmed' AND c.deleted=0 ORDER BY o.start", pid):
        c = library.get_clip(o["clip_id"])
        seg = c["segments"][0]
        out.append(o | {"title": c["title"], "kind": c["kind"], "origin": seg,
                        "offset": round(o["start"] - seg["start"], 3)})
    return out


# ---- discovery ---------------------------------------------------------------------------
def discover(series_id: str, min_s: float = 8.0) -> list[dict]:
    """Stretches of sound that sources of the series share, grouped into candidate
    parts: [{origin {source_id,start,end}, members [...], sources, kind}], most shared
    first. Parts already cut as recurring clips are left out."""
    ids = [r["id"] for r in db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created", series_id)]
    prints = {pid: source_print(pid) for pid in ids}
    ids = [pid for pid in ids if prints[pid] is not None and len(prints[pid])]
    n = len(ids)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)] if n <= 12 else \
        sorted({(0, j) for j in range(1, n)} | {(i, i + 1) for i in range(n - 1)} | {(i, i + 2) for i in range(n - 2)})
    groups: list[list[dict]] = []

    def place(seg: dict) -> int:
        for gi, g in enumerate(groups):
            for s in g:
                if s["source_id"] == seg["source_id"]:
                    inter = min(s["end"], seg["end"]) - max(s["start"], seg["start"])
                    if inter > 0.5 * min(s["end"] - s["start"], seg["end"] - seg["start"]):
                        return gi
        groups.append([])
        return len(groups) - 1

    for i, j in pairs:
        for r in fp.shared_runs(prints[ids[i]], prints[ids[j]], min_s=min_s):
            a = {"source_id": ids[i], "start": r["a_start"], "end": r["a_end"], "score": r["score"]}
            b = {"source_id": ids[j], "start": r["b_start"], "end": r["b_end"], "score": r["score"]}
            ga, gb = place(a), place(b)
            if ga != gb:  # the run joins two groups found earlier
                groups[ga] += groups[gb]
                groups[gb] = []
            for seg in (a, b):
                if not any(s["source_id"] == seg["source_id"] and abs(s["start"] - seg["start"]) < SAME_PLACE_S
                           for s in groups[ga]):
                    groups[ga].append(seg)

    known = _known_spans(series_id)
    durations = {r["id"]: r["duration"] for r in db.rows("SELECT id, duration FROM projects WHERE series_id=?", series_id)}
    out = []
    for g in groups:
        if not g:
            continue
        g.sort(key=lambda s: (ids.index(s["source_id"]), s["start"]))
        origin = g[0]
        if any(k["source_id"] == origin["source_id"] and min(k["end"], origin["end"]) - max(k["start"], origin["start"])
               > 0.5 * (origin["end"] - origin["start"]) for k in known):
            continue
        total = durations.get(origin["source_id"]) or 0
        kind = "intro" if origin["start"] < min(90.0, 0.2 * total or 90.0) else \
            "outro" if total and origin["end"] > total - 90 else "recurring"
        out.append({"origin": {k: origin[k] for k in ("source_id", "start", "end")}, "members": g,
                    "sources": len({s["source_id"] for s in g}), "of": n, "kind": kind,
                    "duration": round(origin["end"] - origin["start"], 2)})
    return sorted(out, key=lambda c: (-c["sources"], -c["duration"]))


def _known_spans(series_id: str) -> list[dict]:
    """Where recurring clips of the series already are: their origins and occurrences."""
    spans = []
    for c in library.clips(series_id=series_id):
        if c["recurring"]:
            spans += c["segments"]
            spans += [o for o in occurrences(c["id"]) if o["status"] != "rejected"]
    return spans


# ---- reuse in dubbing --------------------------------------------------------------------
EDGE_S = 0.3  # a line may overhang an occurrence by this much and still be inside it


def link(pid: str, sents: list[dict], lang: str) -> int:
    """Mark the lines of ``pid`` that lie inside a confirmed occurrence as ``linked`` to
    the matching line of the part's origin, and give them the origin's translation into
    ``lang``: a recurring part is translated and voiced once, at its origin. Lines only
    partly inside stay ordinary. Returns how many lines were linked."""
    n = 0
    for o in confirmed_in(pid):
        seg, off = o["origin"], o["offset"]
        name = (db.row("SELECT name FROM projects WHERE id=?", seg["source_id"]) or {}).get("name")
        olines = db.rows("SELECT s.id, s.start, s.end, t.text AS tr FROM sentences s LEFT JOIN translations t"
                         " ON t.project_id=s.project_id AND t.sentence_id=s.id AND t.lang=?"
                         " WHERE s.project_id=? AND s.start >= ? AND s.end <= ?",
                         lang, seg["source_id"], seg["start"] - EDGE_S, seg["end"] + EDGE_S)
        for s in sents:
            if s.get("linked") or s["start"] < o["start"] - EDGE_S or s["end"] > o["end"] + EDGE_S:
                continue
            if seg["source_id"] == pid and seg["start"] - EDGE_S <= s["start"] and s["end"] <= seg["end"] + EDGE_S:
                continue  # the origin itself
            a, b = s["start"] - off, s["end"] - off  # this line's time at the origin
            best, best_ov = None, 0.5 * (b - a)
            for ol in olines:
                ov = min(b, ol["end"]) - max(a, ol["start"])
                if ov > best_ov:
                    best, best_ov = ol, ov
            s["linked"] = {"clip_id": o["clip_id"], "title": o["title"], "kind": o["kind"],
                           "source_id": seg["source_id"], "source_name": name, "line_id": best["id"] if best else None}
            s["tr"] = (best["tr"] or "") if best else ""
            s["tr_locked"], s["tr_provenance"] = 1, "linked"
            n += 1
    return n


def origin_takes(sents: list[dict], lang: str) -> dict[int, dict]:
    """For linked lines: {local line id: the origin line's chosen take in ``lang``}."""
    from . import voice  # (voice imports project)
    by_source: dict[str, dict[int, dict]] = {}
    out = {}
    for s in sents:
        ln = s.get("linked")
        if not ln or ln["line_id"] is None:
            continue
        src = ln["source_id"]
        if src not in by_source:
            by_source[src] = {t["sentence_id"]: t for t in voice.lines_takes(src, chosen_only=True, lang=lang)}
        t = by_source[src].get(ln["line_id"])
        if t:
            out[s["id"]] = t
    return out
