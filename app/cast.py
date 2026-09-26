"""The cast: characters that belong to a work, not to a video.

A **character** (``cast``) lives in a work (a series, or a standalone video's own
single work) with a portable ``uid``: name, gender, role, notes, whether it needs a
dub, and its name in each target language. A source's diarizer finds voices as labels
(``SPEAKER_00``); an **appearance** says which character a label is in that source.
Lines keep their label; a line's character is its source's appearance for that label.

When a source's speakers arrive (``ensure_for_source``), each label is compared with
the work's characters by voice (the diarizer's centroid embeddings, the same model for
every source): a close match becomes a **proposed** appearance a person confirms or
rejects; otherwise the label gets a new character. Nothing links two videos' voices
without a person confirming (manual truth).

Characters created from a diarizer label are ``auto`` until a person edits them; an auto
character left without appearances is removed, a person's character never is.
"""
from __future__ import annotations

import json
import time

import numpy as np

from . import db

# Cosine of the diarizer's centroid embeddings. Measured: Neil in two 6 Minute English
# episodes 0.72; two different female presenters (Georgie vs Pippa) 0.45; camille's two
# speakers 0.10. Above this a voice is *proposed* as the character, never linked.
MATCH = 0.55
PALETTE = 8
STATUSES = ("proposed", "confirmed")
EDITABLE = ("name", "gender", "important", "role", "notes")


# ---- reading -------------------------------------------------------------------------------
def get(uid: str) -> dict:
    c = db.row("SELECT * FROM cast WHERE uid=?", uid)
    if not c:
        raise KeyError(uid)
    c["names"] = {r["lang"]: r["name"] for r in db.rows("SELECT lang, name FROM cast_names WHERE character_uid=?", uid)}
    return c


def of_work(sid: str) -> list[dict]:
    """The work's characters, each with where it appears."""
    out = []
    for r in db.rows("SELECT uid FROM cast WHERE series_id=? ORDER BY created", sid):
        c = get(r["uid"])
        c["appearances"] = db.rows(
            "SELECT a.source_id, a.label, a.status, a.score, a.talk_s, p.name AS source_name, p.position"
            " FROM appearances a JOIN projects p ON p.id=a.source_id WHERE a.character_uid=? ORDER BY p.position, p.created",
            c["uid"])
        c["talk_s"] = round(sum(a["talk_s"] or 0 for a in c["appearances"]), 1)
        out.append(c)
    return out


def for_source(pid: str) -> list[dict]:
    """This source's speakers: label, its character's fields, and the link's status."""
    out = []
    for a in db.rows("SELECT * FROM appearances WHERE source_id=? ORDER BY talk_s DESC", pid):
        c = get(a["character_uid"])
        others = db.row("SELECT COUNT(*) n FROM appearances WHERE character_uid=? AND source_id<>?", c["uid"], pid)["n"]
        out.append({**{k: c[k] for k in ("uid", "name", "gender", "important", "color", "role", "notes", "names", "auto")},
                    "label": a["label"], "status": a["status"], "score": a["score"], "talk_s": a["talk_s"] or 0,
                    "elsewhere": others, "character_uid": c["uid"]})
    return out


def character_of(pid: str, label: str | None) -> dict | None:
    if not label:
        return None
    a = db.row("SELECT character_uid FROM appearances WHERE source_id=? AND label=?", pid, label)
    return get(a["character_uid"]) if a else None


def labels_of(pid: str) -> dict[str, dict]:
    """{label: character} for a source (important, gender, name… come from the character)."""
    return {s["label"]: s for s in for_source(pid)}


# ---- voice matching ------------------------------------------------------------------------
def _centroids(pid: str) -> dict[str, np.ndarray]:
    from . import project  # (project imports this module)
    f = project.pdir(pid) / "diarization.json"
    if not f.exists():
        return {}
    c = json.loads(f.read_text(encoding="utf-8")).get("centroids") or {}
    return {k: np.asarray(v, dtype=np.float32) / (np.linalg.norm(v) or 1.0) for k, v in c.items() if v}


def voiceprint(uid: str, exclude: str | None = None) -> np.ndarray | None:
    """A character's voice: the mean of its confirmed appearances' centroids."""
    vs = []
    for a in db.rows("SELECT source_id, label FROM appearances WHERE character_uid=? AND status='confirmed'", uid):
        if a["source_id"] == exclude:
            continue
        v = _centroids(a["source_id"]).get(a["label"])
        if v is not None:
            vs.append(v)
    if not vs:
        return None
    m = np.mean(vs, axis=0)
    return m / (np.linalg.norm(m) or 1.0)


def matches(pid: str, label: str) -> list[dict]:
    """The work's other characters ranked by voice similarity to this label."""
    v = _centroids(pid).get(label)
    sid = _work(pid)
    if v is None:
        return []
    out = []
    for r in db.rows("SELECT uid, name FROM cast WHERE series_id=?", sid):
        vp = voiceprint(r["uid"], exclude=pid)
        if vp is not None:
            out.append({"uid": r["uid"], "name": r["name"], "score": round(float(v @ vp), 3)})
    return sorted(out, key=lambda x: -x["score"])


# ---- writing -------------------------------------------------------------------------------
def _work(pid: str) -> str:
    p = db.row("SELECT series_id FROM projects WHERE id=?", pid)
    if not p or not p["series_id"]:
        raise ValueError("the source has no work")
    return p["series_id"]


def create(sid: str, name: str, gender: str | None = None, important: bool = True, auto: bool = False) -> dict:
    n = db.row("SELECT COUNT(*) n FROM cast WHERE series_id=?", sid)["n"]
    uid = db.new_uid()
    db.run("INSERT INTO cast (uid,series_id,name,gender,important,color,auto,created,updated) VALUES (?,?,?,?,?,?,?,?,?)",
           uid, sid, name.strip() or f"Speaker {n + 1}", gender, int(important), n % PALETTE, int(auto), time.time(), time.time())
    return get(uid)


def ensure_for_source(pid: str, talk: dict[str, float]) -> dict:
    """Give every speaker label of a source an appearance: a close voice match among the
    work's characters is proposed, otherwise a new character is made. Existing
    appearances keep their link (manual truth) and only refresh their talk time."""
    sid = _work(pid)
    made, proposed = 0, 0
    taken = {a["character_uid"] for a in db.rows("SELECT character_uid FROM appearances WHERE source_id=?", pid)}
    for label in sorted(talk, key=lambda k: -talk[k]):
        a = db.row("SELECT * FROM appearances WHERE source_id=? AND label=?", pid, label)
        if a:
            db.run("UPDATE appearances SET talk_s=? WHERE source_id=? AND label=?", talk[label], pid, label)
            continue
        best = next((m for m in matches(pid, label) if m["uid"] not in taken), None)
        if best and best["score"] >= MATCH:
            uid, status, score = best["uid"], "proposed", best["score"]
            proposed += 1
        else:
            n = db.row("SELECT COUNT(*) n FROM cast WHERE series_id=?", sid)["n"]
            uid, status, score = create(sid, f"Speaker {n + 1}", auto=True)["uid"], "confirmed", None
            made += 1
        taken.add(uid)
        db.run("INSERT INTO appearances (source_id,label,character_uid,score,status,talk_s,updated) VALUES (?,?,?,?,?,?,?)",
               pid, label, uid, score, status, talk[label], time.time())
    return {"new": made, "proposed": proposed}


def update(uid: str, **changes) -> dict:
    get(uid)
    for k, v in changes.items():
        if k in EDITABLE and v is not None:
            db.run(f"UPDATE cast SET {k}=?, auto=0, updated=? WHERE uid=?", int(v) if isinstance(v, bool) else v, time.time(), uid)
    return get(uid)


def set_name(uid: str, lang: str, name: str) -> dict:
    """The character's name as written in a target language ("Neil" → "ኒል")."""
    get(uid)
    if name.strip():
        db.run("INSERT INTO cast_names (character_uid,lang,name) VALUES (?,?,?) ON CONFLICT (character_uid,lang)"
               " DO UPDATE SET name=excluded.name", uid, lang, name.strip())
    else:
        db.run("DELETE FROM cast_names WHERE character_uid=? AND lang=?", uid, lang)
    db.run("UPDATE cast SET auto=0, updated=? WHERE uid=?", time.time(), uid)
    return get(uid)


def _appearance(pid: str, label: str) -> dict:
    a = db.row("SELECT * FROM appearances WHERE source_id=? AND label=?", pid, label)
    if not a:
        raise KeyError(f"{pid}/{label}")
    return a


def confirm(pid: str, label: str) -> dict:
    """Yes: this label is that character."""
    _appearance(pid, label)
    db.run("UPDATE appearances SET status='confirmed', updated=? WHERE source_id=? AND label=?", time.time(), pid, label)
    return _appearance(pid, label)


def link(pid: str, label: str, uid: str) -> dict:
    """A person says which character this label is (confirmed)."""
    a = _appearance(pid, label)
    c = get(uid)
    if c["series_id"] != _work(pid):
        raise ValueError("that character belongs to another work")
    db.run("UPDATE appearances SET character_uid=?, status='confirmed', score=NULL, updated=? WHERE source_id=? AND label=?",
           uid, time.time(), pid, label)
    _drop_if_orphan(a["character_uid"])
    return _appearance(pid, label)


def detach(pid: str, label: str) -> dict:
    """No / not them: the label becomes a character of its own (new, confirmed)."""
    a = _appearance(pid, label)
    c = create(_work(pid), "", auto=True)
    db.run("UPDATE appearances SET character_uid=?, status='confirmed', score=NULL, updated=? WHERE source_id=? AND label=?",
           c["uid"], time.time(), pid, label)
    _drop_if_orphan(a["character_uid"])
    return _appearance(pid, label)


def merge(src_uid: str, into_uid: str) -> dict:
    """Two characters are one person: every appearance and name moves to ``into``."""
    a, b = get(src_uid), get(into_uid)
    if a["series_id"] != b["series_id"] or src_uid == into_uid:
        raise ValueError("can only merge two different characters of the same work")
    db.run("UPDATE appearances SET character_uid=? WHERE character_uid=?", into_uid, src_uid)
    db.run("INSERT OR IGNORE INTO cast_names (character_uid,lang,name) SELECT ?, lang, name FROM cast_names WHERE character_uid=?",
           into_uid, src_uid)
    _delete(src_uid)
    return get(into_uid)


def merge_labels(pid: str, source: str, into: str) -> None:
    """In one source, two diarizer clusters are one voice: the lines move to ``into``."""
    a, b = _appearance(pid, source), _appearance(pid, into)
    db.run("UPDATE sentences SET speaker=? WHERE project_id=? AND speaker=?", into, pid, source)
    db.run("UPDATE appearances SET talk_s=COALESCE(talk_s,0)+? WHERE source_id=? AND label=?", a["talk_s"] or 0, pid, into)
    db.run("DELETE FROM appearances WHERE source_id=? AND label=?", pid, source)
    if a["character_uid"] != b["character_uid"]:
        _drop_if_orphan(a["character_uid"])


def _drop_if_orphan(uid: str) -> None:
    c = db.row("SELECT auto FROM cast WHERE uid=?", uid)
    if c and c["auto"] and not db.row("SELECT 1 FROM appearances WHERE character_uid=?", uid):
        _delete(uid)


def _delete(uid: str) -> None:
    db.run("DELETE FROM cast_names WHERE character_uid=?", uid)
    db.run("DELETE FROM cast WHERE uid=?", uid)


def move_source(pid: str, old_sid: str, new_sid: str) -> None:
    """A source moves to another work: characters only it has go with it; ones it
    shares with other sources are copied (the old work keeps its own). A voice that
    arrives as an untouched auto character and sounds like one the work already has is
    proposed as that character."""
    for a in db.rows("SELECT * FROM appearances WHERE source_id=?", pid):
        uid = a["character_uid"]
        elsewhere = db.row("SELECT 1 FROM appearances WHERE character_uid=? AND source_id<>?", uid, pid)
        if not elsewhere:
            db.run("UPDATE cast SET series_id=? WHERE uid=?", new_sid, uid)
            if db.row("SELECT auto FROM cast WHERE uid=?", uid)["auto"]:
                taken = {x["character_uid"] for x in db.rows("SELECT character_uid FROM appearances WHERE source_id=?", pid)}
                best = next((m for m in matches(pid, a["label"]) if m["uid"] not in taken), None)
                if best and best["score"] >= MATCH:
                    db.run("UPDATE appearances SET character_uid=?, status='proposed', score=?, updated=?"
                           " WHERE source_id=? AND label=?", best["uid"], best["score"], time.time(), pid, a["label"])
                    _drop_if_orphan(uid)
            continue
        c = get(uid)
        copy = create(new_sid, c["name"], c["gender"], bool(c["important"]), auto=bool(c["auto"]))
        db.run("UPDATE cast SET role=?, notes=?, color=? WHERE uid=?", c["role"], c["notes"], c["color"], copy["uid"])
        for lang, name in c["names"].items():
            set_name(copy["uid"], lang, name)
        db.run("UPDATE appearances SET character_uid=? WHERE source_id=? AND label=?", copy["uid"], pid, a["label"])
