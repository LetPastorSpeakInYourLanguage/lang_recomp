"""Voice banks: the recorded lines a character's cloned voice is made from.

A bank belongs to the character, not to a video. It gathers the character's clean
lines from every source where the character's appearance is confirmed (longest first,
taking turns between sources so one episode's room sound does not dominate) until
about ``TARGET_S`` seconds, and keeps a few other lines aside to judge likeness. Each
line is cut once from its source's vocal stem into a small file under the work
(``data/works/<work uid>/cast/<character uid>/``), so the bank keeps working if a
source is removed and travels with the work when it is shared.

A person can pin a line into the bank or exclude one; rebuilding keeps their choices.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np

from . import cast, db, project

TARGET_S = 12.0
HELD_OUT = 6
SR = 44100


def _clean(text: str) -> bool:
    return text[:1].isupper() and text.rstrip()[-1:] in ".?!"


def _dir(uid: str) -> Path:
    c = cast.get(uid)
    w = db.row("SELECT uid FROM series WHERE id=?", c["series_id"])
    d = db.DATA / "works" / (w["uid"] if w else c["series_id"]) / "cast" / uid
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidates(uid: str) -> list[dict]:
    """Lines the character speaks in its confirmed appearances that make good samples."""
    out = []
    for a in db.rows("SELECT a.source_id, a.label, p.uid AS source_uid FROM appearances a JOIN projects p ON p.id=a.source_id"
                     " WHERE a.character_uid=? AND a.status='confirmed'", uid):
        if not (project.pdir(a["source_id"]) / "vocals.flac").exists():
            continue
        for s in db.rows("SELECT id, start, end, text, reviewed FROM sentences WHERE project_id=? AND speaker=?",
                         a["source_id"], a["label"]):
            secs = s["end"] - s["start"]
            if 1.0 <= secs <= 12.0:
                out.append(s | {"source_id": a["source_id"], "source_uid": a["source_uid"], "secs": round(secs, 3),
                                "clean": _clean(s["text"])})
    return out


def rows(uid: str, role: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM cast_bank WHERE character_uid=?", [uid]
    if role:
        sql, args = sql + " AND role=?", [*args, role]
    return db.rows(sql + " ORDER BY added", *args)


def rebuild(uid: str) -> list[dict]:
    """Refill the bank and held-out lines, keeping what a person pinned or excluded."""
    keep = {(r["source_id"], r["line_id"]): r for r in rows(uid) if r["manual"]}
    db.run("DELETE FROM cast_bank WHERE character_uid=? AND manual=0", uid)
    cands = [c for c in candidates(uid) if (c["source_id"], c["id"]) not in keep]
    # clean, reviewed lines first; longest first within each source; sources take turns
    by: dict[str, list[dict]] = {}
    for c in sorted(cands, key=lambda c: (not c["clean"], not c["reviewed"], -c["secs"])):
        by.setdefault(c["source_id"], []).append(c)
    order: list[dict] = []
    while any(by.values()):
        for src in list(by):
            if by[src]:
                order.append(by[src].pop(0))
    total = sum(r["end"] - r["start"] for r in keep.values() if r["role"] == "bank")
    held = sum(1 for r in keep.values() if r["role"] == "heldout")
    for c in order:
        if total < TARGET_S and c["clean"]:
            role, total = "bank", total + c["secs"]
        elif held < HELD_OUT:
            role, held = "heldout", held + 1
        else:
            continue
        _add(uid, c, role, manual=False)
    return rows(uid)


def _add(uid: str, c: dict, role: str, manual: bool) -> None:
    path = _dir(uid) / f"{c['source_uid'][:12]}-{c['id']}.flac"
    if not path.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['start']:.3f}", "-to", f"{c['end']:.3f}",
                        "-i", str(project.pdir(c["source_id"]) / "vocals.flac"), "-ac", "1", "-ar", str(SR), str(path)],
                       check=True)
    db.run("INSERT OR REPLACE INTO cast_bank (character_uid,source_id,line_id,start,end,text,role,manual,path,added)"
           " VALUES (?,?,?,?,?,?,?,?,?,?)", uid, c["source_id"], c["id"], c["start"], c["end"], c["text"], role,
           int(manual), str(path), time.time())


def pin(uid: str, source_id: str, line_id: int, role: str = "bank") -> list[dict]:
    """A person puts a line into the bank (or held-out set), or excludes it."""
    if role not in ("bank", "heldout", "excluded"):
        raise ValueError("role must be bank, heldout or excluded")
    c = next((x for x in candidates(uid) if x["source_id"] == source_id and x["id"] == line_id), None)
    if c is None:
        raise ValueError("that line is not one of this character's usable lines (1–12 s, confirmed appearance)")
    _add(uid, c, role, manual=True)
    return rows(uid)


def _decode(path: str | Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _write(x: np.ndarray, path: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", str(path)],
                   input=x.astype(np.float32).tobytes(), check=True)


def job_files(uid: str, name: str, dest: Path) -> dict | None:
    """The bank as one wav (lines joined by short pauses) and the held-out lines as
    wavs, written to ``dest`` for a voice job: the plan entry, or None if no bank."""
    bank = rows(uid, "bank") or (rebuild(uid) and rows(uid, "bank"))
    if not bank:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(0.25 * SR), dtype=np.float32)
    bank_file = dest / f"bank_{name}.wav"
    _write(np.concatenate([np.concatenate([_decode(r["path"]), gap]) for r in bank]), bank_file)
    held = rows(uid, "heldout") or bank
    held_files = []
    for k, r in enumerate(held):
        f = dest / f"held_{name}_{k}.wav"
        _write(_decode(r["path"]), f)
        held_files.append(f)
    return {"bank_file": bank_file.name, "bank_text": " ".join(r["text"] for r in bank),
            "heldout_files": [f.name for f in held_files], "sources": len({r["source_id"] for r in bank}),
            "files": [bank_file, *held_files]}
