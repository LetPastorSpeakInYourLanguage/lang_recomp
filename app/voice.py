"""Voicing: queue the voice stage, pull its takes back in, pick takes.

A take belongs to a line and remembers the Amharic text it was made from, so an
edited translation shows its old takes as stale instead of silently mismatched.
"""
from __future__ import annotations

import json
import shutil
import statistics
import time

from . import db, project, settings
from .translate.ethiopic import am_syllables

SCHEMA = """
CREATE TABLE IF NOT EXISTS takes (
  project_id TEXT, sentence_id INTEGER, job_id TEXT, take INTEGER, path TEXT, text TEXT,
  sim REAL, cer REAL, dur REAL, dur_s REAL, asr TEXT, chosen INTEGER DEFAULT 0, created REAL,
  PRIMARY KEY (project_id, sentence_id, job_id, take)
);
"""
ENGINE = {"model": "k2-fsa/OmniVoice", "steps": 16, "speed": 1.4, "takes": 2}


def _init() -> None:
    db.conn().executescript(SCHEMA)


def _clean(text: str) -> bool:
    return text[:1].isupper() and text.rstrip()[-1:] in ".?!"


def characters_plan(pid: str) -> dict:
    """Per important character: ~10 s of their longest clean lines as the voice
    sample (timbre), and other lines held out to judge likeness fairly."""
    chars = {c["label"]: c for c in db.rows("SELECT * FROM characters WHERE project_id=?", pid)}
    by: dict[str, list[dict]] = {}
    for s in project.sentences(pid):
        if s["speaker"] in chars and chars[s["speaker"]]["important"]:
            by.setdefault(s["speaker"], []).append(s)
    out = {}
    for spk, ss in by.items():
        pool = [s for s in ss if _clean(s["text"]) and 1.0 <= s["slot_s"] <= 12] or \
               [s for s in ss if 1.0 <= s["slot_s"] <= 12]
        bank, dur = [], 0.0
        for s in sorted(pool, key=lambda s: -s["slot_s"]):
            if dur >= 10:
                break
            bank.append(s)
            dur += s["slot_s"]
        if not bank:
            continue
        bank.sort(key=lambda s: s["start"])
        held = [s for s in pool if s not in bank][:6] or bank
        out[spk] = {"bank": [[s["start"], s["end"]] for s in bank],
                    "bank_text": " ".join(s["text"] for s in bank),
                    "heldout": [[s["start"], s["end"]] for s in held]}
    return out


def queue(pid: str, root_id: str | None = None, ids: list[int] | None = None, takes: int | None = None) -> dict:
    _init()
    r = settings.root(root_id)
    q = project.queue(r["id"])
    vocals = project.pdir(pid) / "vocals.flac"
    if not vocals.exists():
        raise RuntimeError("no vocal stem yet: load the analysis results first")
    chars = characters_plan(pid)
    lines = [s for s in project.sentences(pid) if s["am"] and s["mode"] == "dub" and s["speaker"] in chars
             and (not ids or s["id"] in ids)]
    if not lines:
        raise RuntimeError("nothing to voice: translate the lines of important characters first")
    plan = {"engine": ENGINE | ({"takes": takes} if takes else {}), "characters": chars,
            "lines": [{k: s[k] for k in ("id", "speaker", "am", "start", "end", "slot_s")} for s in lines]}
    path = project.pdir(pid) / "voice_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    job = q.submit("voice", {"project": pid}, files=[path], shared=[q.put_media(pid, vocals)])
    project.record_job(pid, job, "voice", role="voice", root=r["id"])
    return {"job": job, "lines": len(lines), "root": r["id"]}


def ingest(pid: str) -> int:
    """Copy takes from finished voice jobs not yet loaded; newest job wins the pick."""
    _init()
    loaded = set(db.meta(pid).get("voice_loaded", []))
    n = 0
    for j in sorted(db.rows("SELECT * FROM jobs WHERE project_id=? AND stage='voice'", pid), key=lambda j: j["created"]):
        if j["id"] in loaded:
            continue
        q = project.job_queue(j)
        if q.status(j["id"]).get("state") != "done":
            continue
        out = q.out_dir(j["id"])
        summary = json.loads((out / "voice.json").read_text(encoding="utf-8"))
        dst = project.pdir(pid) / "takes"
        dst.mkdir(exist_ok=True)
        for sid, line in summary["lines"].items():
            db.run("UPDATE takes SET chosen=0 WHERE project_id=? AND sentence_id=?", pid, int(sid))
            for t in line["takes"]:
                local = dst / f"{j['id']}_{sid}_t{t['take']}.wav"
                shutil.copy2(out / t["file"], local)
                db.run("INSERT OR REPLACE INTO takes (project_id,sentence_id,job_id,take,path,text,sim,cer,dur,dur_s,"
                       "asr,chosen,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", pid, int(sid), j["id"], t["take"],
                       str(local), t["text"], t.get("sim"), t.get("cer"), t.get("dur"), t.get("dur_s"),
                       t.get("asr"), int(t["take"] == line["best"]), time.time())
                n += 1
        loaded.add(j["id"])
        db.set_meta(pid, voice_loaded=sorted(loaded))
    if n:
        calibrate_rate(pid)
    return n


def calibrate_rate(pid: str) -> None:
    """Measure the voice's real Amharic rate (fidels per second) from the chosen
    takes, so the Translate meter predicts lengths for this engine and speed."""
    rates = [am_syllables(t["text"]) / t["dur_s"] for t in lines_takes(pid, chosen_only=True)
             if t["dur_s"] and am_syllables(t["text"]) > 4]
    if len(rates) >= 3:
        db.set_meta(pid, am_rate=round(statistics.median(rates), 2))


def lines_takes(pid: str, chosen_only: bool = False) -> list[dict]:
    _init()
    sql = "SELECT rowid AS take_id, * FROM takes WHERE project_id=?" + (" AND chosen=1" if chosen_only else "")
    return db.rows(sql + " ORDER BY sentence_id, created, take", pid)


def choose(pid: str, take_id: int) -> None:
    t = db.row("SELECT sentence_id FROM takes WHERE rowid=? AND project_id=?", take_id, pid)
    if not t:
        raise ValueError("no such take")
    db.run("UPDATE takes SET chosen=(rowid=?) WHERE project_id=? AND sentence_id=?", take_id, pid, t["sentence_id"])
