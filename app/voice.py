"""Voicing: queue the voice stage, pull its takes back in, pick takes.

A take belongs to a line and a language, and remembers the text it was made from,
so an edited translation shows its old takes as stale instead of silently mismatched.
"""
from __future__ import annotations

import json
import shutil
import statistics
import time

from . import banks, cast, db, langs, project, settings
from .translate.length import syllables

ENGINE = {"model": "k2-fsa/OmniVoice", "steps": 16, "speed": 1.4, "takes": 2, "batch": 1,  # batch: takes per call (T4: no gain above 1, docs/CERTIFICATION.md)
          # decision 46: native speech, then Seed-VC into the character's voice, where the language has native
          # voices (worker/lb_worker/native_vc.py); "clone" = OmniVoice straight from the bank everywhere
          "path": "native_vc", "native_speed": 1.0, "vc_steps": 25}


def _init() -> None:
    db.conn()  # the takes table lives in db.SCHEMA


def _clean(text: str) -> bool:
    return text[:1].isupper() and text.rstrip()[-1:] in ".?!"


def characters_plan(pid: str, dest=None) -> dict:
    """Per important character speaking in this source: the character's voice bank
    (its lines from every episode it is confirmed in, see app/banks.py) and held-out
    lines, written as files to ``dest`` for the job; plus, as before, ~10 s of this
    source's own clean lines as spans, which workers from before banks still use."""
    chars = cast.labels_of(pid)
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
        if dest is not None:
            entry = banks.job_files(chars[spk]["uid"], spk, dest)
            if entry:
                out[spk] |= {k: entry[k] for k in ("bank_file", "bank_text", "heldout_files", "sources")}
                out[spk]["_files"] = entry["files"]
    return out


def queue(pid: str, root_id: str | None = None, ids: list[int] | None = None, takes: int | None = None,
          lang: str | None = None) -> dict:
    _init()
    lang = project.lang_or_primary(pid, lang)
    r = settings.root(root_id)
    q = project.queue(r["id"])
    vocals = project.stem(pid, "vocals")
    if not vocals.exists():
        raise RuntimeError("no vocal stem yet: load the analysis results first")
    dest = project.pdir(pid) / "voice_banks"
    chars = characters_plan(pid, dest)
    bank_files = [f for c in chars.values() for f in c.pop("_files", [])]
    lines = lines_to_voice(pid, lang, chars, ids)
    if not lines:
        raise RuntimeError(f"nothing to voice in {langs.name(lang)}: translate the lines of important characters first")
    # The voice model wants the language's name; the scorer back-transcribes with the
    # language's aligner (a CTC model is a speech recogniser) when one is set.
    engine = ENGINE | ({"takes": takes} if takes else {}) | {
        "lang": lang, "language": langs.name(lang), "asr": settings.aligner(lang) or ""}
    plan = {"engine": engine, "characters": chars,
            "lines": [{"id": s["id"], "speaker": s["speaker"], "text": s["tr"], "start": s["start"],
                       "end": s["end"], "slot_s": s["slot_s"]} for s in lines]}
    path = project.pdir(pid) / "voice_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    job = q.submit("voice", {"project": pid, "lang": lang}, files=[path, *bank_files], shared=[q.put_media(pid, vocals)])
    project.record_job(pid, job, "voice", role="voice", root=r["id"])
    return {"job": job, "lines": len(lines), "root": r["id"], "lang": lang}


def lines_to_voice(pid: str, lang: str, chars: dict, ids: list[int] | None = None) -> list[dict]:
    """Translated lines to dub of the characters in ``chars`` (a recurring part's lines
    are voiced at its origin, not here)."""
    return [s for s in project.sentences(pid, lang) if s["tr"] and s["mode"] == "dub" and s["speaker"] in chars
            and not s["linked"] and (not ids or s["id"] in ids)]


def record_takes(pid: str, lang: str, job_id: str, lines: dict) -> int:
    """Takes made elsewhere and left where they are (e.g. on Drive, by a run):
    ``lines`` = {line id: {"takes": [{take, path, text, sim, cer, dur, dur_s, asr}], "best": take}}.
    The best take of each line becomes the chosen one."""
    n = 0
    for sid, line in lines.items():
        db.run("UPDATE takes SET chosen=0 WHERE project_id=? AND sentence_id=? AND lang=?", pid, int(sid), lang)
        for t in line["takes"]:
            db.run("INSERT OR REPLACE INTO takes (project_id,sentence_id,job_id,take,path,text,sim,cer,dur,dur_s,"
                   "asr,chosen,created,lang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pid, int(sid), job_id, t["take"],
                   str(t["path"]), t["text"], t.get("sim"), t.get("cer"), t.get("dur"), t.get("dur_s"),
                   t.get("asr"), int(t["take"] == line["best"]), time.time(), lang)
            n += 1
    calibrate_rate(pid, lang)
    return n


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
        # Jobs from before languages were data are in the project's primary language.
        lang = (summary.get("engine") or {}).get("lang") or project.get(pid)["tgt_lang"]
        dst = project.pdir(pid) / "takes"
        dst.mkdir(exist_ok=True)
        for sid, line in summary["lines"].items():
            db.run("UPDATE takes SET chosen=0 WHERE project_id=? AND sentence_id=? AND lang=?", pid, int(sid), lang)
            for t in line["takes"]:
                local = dst / f"{j['id']}_{sid}_t{t['take']}.wav"
                shutil.copy2(out / t["file"], local)
                db.run("INSERT OR REPLACE INTO takes (project_id,sentence_id,job_id,take,path,text,sim,cer,dur,dur_s,"
                       "asr,chosen,created,lang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pid, int(sid), j["id"], t["take"],
                       str(local), t["text"], t.get("sim"), t.get("cer"), t.get("dur"), t.get("dur_s"),
                       t.get("asr"), int(t["take"] == line["best"]), time.time(), lang)
                n += 1
        loaded.add(j["id"])
        db.set_meta(pid, voice_loaded=sorted(loaded))
        calibrate_rate(pid, lang)
    return n


def calibrate_rate(pid: str, lang: str) -> None:
    """Measure the voice's real speaking rate in this language (syllables per second)
    from the chosen takes, so the Translate meter predicts lengths for this engine,
    speed and language."""
    rates = [syllables(t["text"], lang) / t["dur_s"] for t in lines_takes(pid, chosen_only=True, lang=lang)
             if t["dur_s"] and syllables(t["text"], lang) > 4]
    if len(rates) >= 3:
        db.set_meta(pid, rates=(db.meta(pid).get("rates") or {}) | {lang: round(statistics.median(rates), 2)})


def lines_takes(pid: str, chosen_only: bool = False, lang: str | None = None) -> list[dict]:
    _init()
    sql = "SELECT rowid AS take_id, * FROM takes WHERE project_id=?" + (" AND chosen=1" if chosen_only else "")
    args: list = [pid]
    if lang:
        sql += " AND lang=?"
        args.append(lang)
    return db.rows(sql + " ORDER BY sentence_id, created, take", *args)


def choose(pid: str, take_id: int) -> None:
    t = db.row("SELECT sentence_id, lang FROM takes WHERE rowid=? AND project_id=?", take_id, pid)
    if not t:
        raise ValueError("no such take")
    db.run("UPDATE takes SET chosen=(rowid=?) WHERE project_id=? AND sentence_id=? AND lang=?",
           take_id, pid, t["sentence_id"], t["lang"])
