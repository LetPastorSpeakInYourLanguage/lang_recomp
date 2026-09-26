"""Project lifecycle: import -> analyze (Colab) -> ingest -> translate.

Each step is a plain function the API calls; long ones run as local tasks.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import cast, chapters as chaps, db, settings, tasks
from .jobs.drive_queue import DriveQueue
from .translate.google_batch import GoogleBatchTranslator
from .translate.length import budget
from .interjections import effective_mode, keep_words, suggest_keep
from .translate.sentences import sentences as regroup

ANALYSIS = ("separate", "asr", "diarize")
_queues: dict[str, DriveQueue] = {}


def queue(root_id: str | None = None) -> DriveQueue:
    """The job queue in a configured job folder (default: the active one)."""
    r = settings.root(root_id)
    q = _queues.get(r["path"])
    if q is None:
        q = _queues[r["path"]] = DriveQueue(r["path"])
    return q


def pdir(pid: str) -> Path:
    d = db.DATA / "projects" / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def single_work(pid: str) -> str:
    """Give a project its own hidden single-source work (a standalone video): the work
    holds its cast and clips, and is what travels when it is shared."""
    p = get(pid)
    sid = db._free_series_id(db.conn(), pid)
    db.run("INSERT INTO series (id,name,kind,src_lang,targets,settings,created,uid) VALUES (?,?,'single',?,?,'{}',?,?)",
           sid, p["name"], p["src_lang"], json.dumps(targets(pid)), time.time(), db.new_uid())
    db.run("UPDATE projects SET series_id=?, position=1 WHERE id=?", sid, pid)
    db.run("UPDATE clips SET series_id=? WHERE source_id=?", sid, pid)
    return sid


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "project"
    base, n = s, 2
    while db.row("SELECT id FROM projects WHERE id=?", s):
        s, n = f"{base}-{n}", n + 1
    return s


# ---- import ------------------------------------------------------------------------------
def create(name: str, source: str, clip_start: float | None, clip_end: float | None,
           max_speakers: int | None, src_lang: str = "en", tgt_lang: str = "am",
           extra_targets: list[str] | tuple = (), series: dict | None = None) -> dict:
    """A new project (a source), imported and analysed in the background. ``series``
    places it in a series: {series_id, position, origin_id, published}; without one it
    gets its own single-source work (a standalone video)."""
    for lang in (src_lang, tgt_lang, *extra_targets):
        check_lang(lang)
    pid = slug(name)
    se = series or {}
    db.run("INSERT INTO projects (id,name,source,src_lang,tgt_lang,max_speakers,clip_start,clip_end,created,"
           "series_id,position,origin_id,published,uid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           pid, name, source, src_lang, tgt_lang, max_speakers, clip_start, clip_end, time.time(),
           se.get("series_id"), se.get("position"), se.get("origin_id"), se.get("published"), db.new_uid())
    extra = [t for t in extra_targets if t not in (tgt_lang, src_lang)]
    if extra:
        db.set_meta(pid, targets=extra)
    if not se.get("series_id"):
        single_work(pid)
    tasks.start(pid, "import", _import, pid, serial="import")  # downloads queue up, one at a time
    return get(pid)


def _import(pid: str, update) -> None:
    p = get(pid)
    d = pdir(pid)
    video = d / "clip.mp4"
    src = p["source"].strip()
    if re.match(r"https?://", src):
        update(0.05, "downloading with yt-dlp")
        cmd = ["yt-dlp", "--js-runtimes", "node", "-f", "bv*[height<=720]+ba/b[height<=720]",
               "--merge-output-format", "mp4", "--write-auto-subs", "--sub-langs", p["src_lang"],
               "--sub-format", "vtt", "-o", str(d / "clip.%(ext)s"), "--retries", "10", "--fragment-retries", "10",
               # a clip range downloads through ffmpeg: let it reconnect on a flaky link
               "--downloader-args", "ffmpeg_i:-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 30"]
        if p["clip_start"] is not None or p["clip_end"] is not None:
            cmd += ["--download-sections", f"*{p['clip_start'] or 0}-{p['clip_end'] or 'inf'}",
                    "--force-keyframes-at-cuts"]
        for attempt in range(1, 4):  # a dropped connection mid-download is common here; try again
            try:
                _run(cmd + ["--", src])
                break
            except RuntimeError:
                if attempt == 3:
                    raise
                update(0.05, f"download failed, retrying ({attempt + 1}/3)")
                time.sleep(5 * attempt)
    else:
        update(0.05, "copying local file")
        path = Path(src)
        if p["clip_start"] is not None or p["clip_end"] is not None:
            _run(["ffmpeg", "-v", "error", "-y", "-ss", str(p["clip_start"] or 0),
                  *(["-to", str(p["clip_end"])] if p["clip_end"] else []), "-i", str(path),
                  "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(video)])
        else:
            shutil.copy2(path, video)
    update(0.7, "extracting audio")
    audio = d / "clip.flac"
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "44100",
          "-c:a", "flac", str(audio)])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout or 0)
    db.run("UPDATE projects SET video=?, audio=?, duration=? WHERE id=?", str(video), str(audio), dur, pid)
    from . import recurring  # (imports project) — fingerprint now, so finding recurring parts is quick later
    try:
        recurring.source_print(pid)
    except Exception as e:  # never fail an import over it; it is computed on demand again
        update(None, f"fingerprint skipped: {e}")
    update(0.85, f"sending audio to {settings.root()['name']}")
    analyze(pid)


def retry_import(pid: str) -> str:
    """Run a failed (or interrupted) import again: download, audio, analysis."""
    get(pid)
    if tasks.busy(pid, "import"):
        raise ValueError("this video is already being imported")
    return tasks.start(pid, "import", _import, pid, serial="import")


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{Path(cmd[0]).name} exit {p.returncode}: {p.stderr[-500:]}")


# ---- analysis on Colab -------------------------------------------------------------------
def analyze(pid: str, root_id: str | None = None) -> dict:
    p = get(pid)
    r = settings.root(root_id)
    q = queue(r["id"])
    audio = q.put_media(pid, p["audio"])
    # large-v3-turbo: nearly large-v3 accuracy at a fraction of the CPU time.
    model = "large-v3" if r["kind"] == "colab" else "large-v3-turbo"
    sep = q.submit("separate", {"project": pid}, shared=[audio])
    asr = q.submit("asr", {"project": pid, "model": model, "language": p["src_lang"]},
                   shared=[q.out_ref(sep, "vocals.flac")], after=[sep])
    words_ref, words_job = q.out_ref(asr, "asr.json"), asr
    jobs = [("separate", sep), ("asr", asr)]
    model_id = settings.aligner(p["src_lang"])
    if model_id:  # pin every word to the audio before speakers are assigned
        al = q.submit("align", {"project": pid, "model": model_id, "language": p["src_lang"]},
                      shared=[q.out_ref(sep, "vocals.flac"), q.out_ref(asr, "asr.json")], after=[sep, asr])
        words_ref, words_job = q.out_ref(al, "aligned.json"), al
        jobs.append(("align", al))
    dia = diarize(pid, q, sep, words_ref, words_job, p["max_speakers"])
    jobs.append(("diarize", dia))
    for stage, jid in jobs:
        record_job(pid, jid, stage, role="analysis", root=r["id"])
    return dict(jobs) | {"root": r["id"]}


def diarize(pid: str, q: DriveQueue, sep: str, words_ref: str, words_job: str, max_speakers: int | None) -> str:
    params = {"project": pid} | ({"max_speakers": max_speakers} if max_speakers else {})
    return q.submit("diarize", params, shared=[q.out_ref(sep, "vocals.flac"), words_ref], after=[sep, words_job])


def realign(pid: str, root_id: str | None = None) -> dict:
    """Align the existing transcript's words (no re-separation or re-transcription)
    and re-assign speakers with the aligned times. Load results when it finishes."""
    p = get(pid)
    model_id = settings.aligner(p["src_lang"])
    if not model_id:
        raise RuntimeError(f"no aligner set for '{p['src_lang']}' (Folders & settings)")
    sep_j, asr_j = latest_job(pid, "separate"), latest_job(pid, "asr")
    if not sep_j or not asr_j:
        raise RuntimeError("run the analysis first")
    r = settings.root(root_id)
    q = queue(r["id"])
    # The inputs may live in another job folder: copy them in as this job's own files.
    vocals = job_queue(sep_j).out_dir(sep_j["id"]) / "vocals.flac"
    words = job_queue(asr_j).out_dir(asr_j["id"]) / "asr.json"
    media = q.put_media(pid, vocals)
    al = q.submit("align", {"project": pid, "model": model_id, "language": p["src_lang"]}, files=[words], shared=[media])
    dia = q.submit("diarize", {"project": pid} | ({"max_speakers": p["max_speakers"]} if p["max_speakers"] else {}),
                   shared=[media, q.out_ref(al, "aligned.json")], after=[al])
    record_job(pid, al, "align", role="analysis", root=r["id"])
    record_job(pid, dia, "diarize", role="analysis", root=r["id"])
    return {"align": al, "diarize": dia, "model": model_id, "root": r["id"]}


def record_job(pid: str, jid: str, stage: str, role: str = "", root: str = "colab") -> None:
    db.run("INSERT OR REPLACE INTO jobs (id,project_id,stage,created,role,root) VALUES (?,?,?,?,?,?)",
           jid, pid, stage, time.time(), role, root)


def latest_job(pid: str, stage: str) -> dict | None:
    return db.row("SELECT * FROM jobs WHERE project_id=? AND stage=? ORDER BY created DESC LIMIT 1", pid, stage)


def job_queue(job: dict) -> DriveQueue:
    return queue(job.get("root") or "colab")


def jobs(pid: str | None = None) -> list[dict]:
    out = []
    sql = "SELECT * FROM jobs" + (" WHERE project_id=?" if pid else "") + " ORDER BY created DESC"
    for j in db.rows(sql, *([pid] if pid else [])):
        try:
            st = job_queue(j).status(j["id"])
        except OSError:
            st = {"state": "unreachable", "error": f"job folder {settings.root(j.get('root'))['path']} not reachable"}
        out.append(j | {"state": st.get("state"), "progress": st.get("progress"),
                        "error": st.get("error"), "result": st.get("result"),
                        "elapsed_s": st.get("elapsed_s"), "heartbeat": st.get("heartbeat")})
    return out


# ---- ingest ------------------------------------------------------------------------------
PALETTE = 8


def ingest(pid: str) -> dict:
    """Pull finished analysis into the DB: sentences, characters, local stems."""
    js = {s: latest_job(pid, s) for s in ANALYSIS}
    for s, j in js.items():
        if not j or job_queue(j).status(j["id"]).get("state") != "done":
            raise RuntimeError(f"{s} is not done yet")
    d = pdir(pid)
    sep, dz = js["separate"], js["diarize"]
    for name in ("vocals.flac", "background.flac"):
        shutil.copy2(job_queue(sep).out_dir(sep["id"]) / name, d / name)
    out = job_queue(dz).out_dir(dz["id"])
    asr = json.loads((out / "asr_spk.json").read_text(encoding="utf-8"))
    dia = json.loads((out / "diarization.json").read_text(encoding="utf-8"))
    (d / "asr_spk.json").write_text(json.dumps(asr, ensure_ascii=False), encoding="utf-8")
    (d / "diarization.json").write_text(json.dumps(dia), encoding="utf-8")
    old = db.rows("SELECT * FROM sentences WHERE project_id=?", pid)
    locked, sents = keep_reviewed(old, regroup(asr))
    kept = carry_over([o for o in old if not o["reviewed"]], sents) | {o["id"]: o["id"] for o in locked}
    db.run("DELETE FROM sentences WHERE project_id=? AND reviewed=0", pid)
    db.many("INSERT INTO sentences (project_id,id,speaker,start,end,text,words,reviewed)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(pid, s["id"], s["speaker"], s["start"], s["end"], s["text"], json.dumps(s["words"]),
              s.get("reviewed", 0)) for s in sents])
    _remap_lines(pid, kept)
    chaps.normalize(pid)  # chapters are times: they keep holding whatever lines now start in them
    sents = locked + sents
    talk: dict[str, float] = {}
    for t in dia["exclusive"]:
        talk[t["speaker"]] = talk.get(t["speaker"], 0) + t["end"] - t["start"]
    # each voice becomes an appearance of a work character: a close match to one the work
    # already has is proposed for a person to confirm, otherwise a new character
    linked = cast.ensure_for_source(pid, talk)
    db.set_meta(pid, ingested_at=time.time())
    return {"sentences": len(sents), "characters": len(talk), "carried_over": len(kept), "cast": linked}


def keep_reviewed(old: list[dict], new: list[dict], max_overlap: float = 0.3) -> tuple[list[dict], list[dict]]:
    """Reviewed lines are the person's final word: a reload never changes them (text,
    speaker, times, merges, translation, takes). New lines that overlap a reviewed
    line by more than ``max_overlap`` of their own length are dropped; the rest get
    fresh ids after the highest id in use. Returns (reviewed lines, new lines to add)."""
    locked = [o for o in old if o["reviewed"]]
    next_id = max([o["id"] for o in old] + [0]) + 1
    out = []
    for s in new:
        span = max(1e-6, s["end"] - s["start"])
        covered = sum(max(0.0, min(s["end"], o["end"]) - max(s["start"], o["start"])) for o in locked)
        if covered / span > max_overlap:
            continue
        s["id"] = next_id
        next_id += 1
        out.append(s)
    return locked, out


def carry_over(old: list[dict], new: list[dict], min_iou: float = 0.6) -> dict[int, int]:
    """Re-running analysis (e.g. re-aligning) must not throw away the work done on
    the lines. Each new line takes over from the old line it overlaps most in time,
    if they share at least ``min_iou`` of their combined span: the reviewed mark
    and, for lines marked reviewed, the edited text and speaker too. Returns
    {old id: new id}; translations and takes follow via `_remap_lines`."""
    kept: dict[int, int] = {}
    used: set[int] = set()
    for s in new:
        best, best_iou = None, min_iou
        for o in old:
            if o["id"] in used:
                continue
            inter = min(s["end"], o["end"]) - max(s["start"], o["start"])
            if inter <= 0:
                continue
            iou = inter / (max(s["end"], o["end"]) - min(s["start"], o["start"]))
            if iou >= best_iou:
                best, best_iou = o, iou
        if best is None:
            continue
        used.add(best["id"])
        kept[best["id"]] = s["id"]
        s["reviewed"] = best["reviewed"]
        if best["reviewed"]:  # the person confirmed this line: their wording and speaker win
            s.update(text=best["text"], speaker=best["speaker"])
    return kept


def _remap_lines(pid: str, kept: dict[int, int]) -> None:
    """Translations and voiced takes follow their line to its new id (via a temporary
    offset, so renumbering can never collide with an id still in use). Rows of lines
    that no longer exist stay behind under the offset, orphaned but not destroyed."""
    off = 1_000_000
    for table in ("takes", "translations"):
        db.run(f"UPDATE {table} SET sentence_id = sentence_id + ? WHERE project_id=? AND sentence_id < ?", off, pid, off)
        for old_id, new_id in kept.items():
            db.run(f"UPDATE {table} SET sentence_id=? WHERE project_id=? AND sentence_id=?", new_id, pid, old_id + off)


# ---- read models -------------------------------------------------------------------------
def get(pid: str) -> dict:
    p = db.row("SELECT * FROM projects WHERE id=?", pid)
    if not p:
        raise KeyError(pid)
    p["meta"] = json.loads(p["meta"] or "{}")
    return p


def targets(pid: str) -> list[str]:
    """The project's target languages, primary first."""
    p = get(pid)
    extra = [t for t in p["meta"].get("targets", []) if t != p["tgt_lang"]]
    return [p["tgt_lang"], *extra]


def check_lang(lang: str) -> str:
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", lang or ""):
        raise ValueError(f"'{lang}' is not a language code; use one such as en, am, om, ti, sw or fr")
    return lang


def add_target(pid: str, lang: str) -> list[str]:
    lang = check_lang(lang.strip().lower())
    ts = targets(pid)
    if lang not in ts and lang != get(pid)["src_lang"]:
        db.set_meta(pid, targets=[*ts[1:], lang])
    return targets(pid)


def lang_or_primary(pid: str, lang: str | None) -> str:
    return lang or get(pid)["tgt_lang"]


def set_translation(pid: str, sid: int, lang: str, text: str | None = None, locked: bool | None = None,
                    provenance: str = "human", force: bool = False) -> bool:
    """Write one line's translation. A machine write never replaces a locked or
    person-written one unless ``force`` (an explicit "re-translate everything").
    Returns whether anything was written."""
    cur = db.row("SELECT * FROM translations WHERE project_id=? AND sentence_id=? AND lang=?", pid, sid, lang)
    if cur and provenance == "machine" and not force and (cur["locked"] or cur["provenance"] != "machine"):
        return False
    new_text = cur["text"] if text is None and cur else (text or "")
    new_locked = int(locked) if locked is not None else (cur["locked"] if cur else 0)
    db.run("INSERT INTO translations (project_id,sentence_id,lang,text,locked,provenance,updated) VALUES (?,?,?,?,?,?,?)"
           " ON CONFLICT (project_id,sentence_id,lang) DO UPDATE SET text=excluded.text, locked=excluded.locked,"
           " provenance=excluded.provenance, updated=excluded.updated",
           pid, sid, lang, new_text, new_locked,
           provenance if text is not None else (cur["provenance"] if cur else provenance), time.time())
    return True


def summary(pid: str) -> dict:
    p = get(pid)
    n = db.row("SELECT COUNT(*) n, SUM(reviewed) rv FROM sentences WHERE project_id=?", pid)
    p["targets"] = targets(pid)
    w = db.row("SELECT kind FROM series WHERE id=?", p["series_id"]) if p.get("series_id") else None
    p["standalone"] = not w or w["kind"] == "single"  # its own hidden work, not a series
    # translated = has words in that language, own or (linked lines) the recurring part's
    per_lang, kept_lines, linked = {}, 0, 0
    for t in p["targets"]:
        ss = sentences(pid, t)
        per_lang[t] = sum(1 for s in ss if s["tr"])
        if t == p["tgt_lang"]:
            kept_lines = sum(1 for s in ss if s["mode"] == "keep")
            linked = sum(1 for s in ss if s["linked"])
    chars = cast.for_source(pid)
    js = jobs(pid)
    analysis = {s: next((j["state"] for j in js if j["stage"] == s), None) for s in ANALYSIS}
    p["counts"] = {"sentences": n["n"] or 0, "translated": per_lang.get(p["tgt_lang"], 0),
                   "translated_by_lang": {t: per_lang.get(t, 0) for t in p["targets"]},
                   "reviewed": n["rv"] or 0, "kept": kept_lines, "linked": linked,
                   "chapters": len(chaps.ensure(pid)) if n["n"] else 0, "characters": len(chars),
                   "genders_set": sum(1 for c in chars if c["gender"])}
    p["analysis"] = analysis
    p["import"] = next((t for t in tasks.list_for(pid) if t["kind"] == "import"), None)
    return p


def rate(pid: str, lang: str) -> float | None:
    """Measured speaking rate for this language's voice (syllables/s), if any."""
    meta = db.meta(pid)
    return (meta.get("rates") or {}).get(lang) or (meta.get("am_rate") if lang == "am" else None)


def sentences(pid: str, lang: str | None = None) -> list[dict]:
    """Lines in time order, each with its translation into ``lang`` (default: the
    primary target) as `tr` / `tr_locked` / `tr_provenance`."""
    lang = lang_or_primary(pid, lang)
    out = db.rows("SELECT s.*, t.text AS tr, t.locked AS tr_locked, t.provenance AS tr_provenance"
                  " FROM sentences s LEFT JOIN translations t"
                  " ON t.project_id=s.project_id AND t.sentence_id=s.id AND t.lang=?"
                  " WHERE s.project_id=? ORDER BY s.start", lang, pid)
    r = rate(pid, lang)
    kw = keep_words()
    chaps.assign(out, chaps.ensure(pid))
    from . import recurring  # (imports project)
    for s in out:
        s["linked"] = None
    recurring.link(pid, out, lang)  # lines of a confirmed recurring part take the origin's translation
    for s in out:
        s.pop("words", None)  # only merge/split need them; keep the list payload small
        for old in ("am", "am_locked"):
            s.pop(old, None)
        s["lang"] = lang
        s["tr"] = s["tr"] or ""
        s["tr_locked"] = s["tr_locked"] or 0
        s["slot_s"] = round(s["end"] - s["start"], 3)
        s["mode_set"] = s["mode"]  # the person's explicit choice, or None
        s["mode"] = effective_mode(s["mode"], s["text"], s["slot_s"], kw)
        s["mode_suggested"] = "keep" if suggest_keep(s["text"], s["slot_s"], kw) else "dub"
        s["budget"] = budget(s["tr"], s["slot_s"], r, lang) if s["tr"] else None
    return out


# ---- translation -------------------------------------------------------------------------
def translate(pid: str, lang: str | None = None, chapter: int | None = None, force: bool = False) -> str:
    """Translate every chapter, or only the one with id ``chapter``."""
    if chapter is not None and chapter not in {c["id"] for c in chaps.ensure(pid)}:
        raise ValueError("no such chapter")
    return tasks.start(pid, "translate", _translate, pid, lang_or_primary(pid, lang), chapter, force)


def _translate(pid: str, lang: str, chapter: int | None, force: bool, update) -> None:
    p = get(pid)
    # lines of a recurring part are translated once, at its origin
    todo = [[s for s in lines if not s["linked"]] for c, lines in chaps.group(sentences(pid, lang), chaps.ensure(pid))
            if chapter is None or c["id"] == chapter]
    todo = [lines for lines in todo if lines]
    tr = GoogleBatchTranslator(p["src_lang"], lang, context=2)
    for i, ch in enumerate(todo):
        update(i / len(todo), f"chapter {i + 1}/{len(todo)}")
        # Context never crosses a chapter break: a chapter is one topic.
        res = tr.translate([{"id": s["id"], "text": s["text"]} for s in ch])
        for s in ch:  # people's wording is never replaced by the engine unless forced
            set_translation(pid, s["id"], lang, res.get(s["id"], ""), locked=False, provenance="machine", force=force)


# ---- merge / split -----------------------------------------------------------------------
def _words(pid: str, s: dict) -> list[dict]:
    """A line's word timings; lines ingested before they were stored get them back
    from the saved transcript by time range."""
    w = json.loads(s.get("words") or "[]")
    if w:
        return w
    f = pdir(pid) / "asr_spk.json"
    if not f.exists():
        return []
    asr = json.loads(f.read_text(encoding="utf-8"))
    return [{"w": x["w"], "start": x["start"], "end": x["end"]} for seg in asr["segments"]
            for x in seg.get("words", []) if x["start"] >= s["start"] - 0.02 and x["end"] <= s["end"] + 0.02]


def merge_next(pid: str, sid: int) -> dict:
    """Join a line with the one after it: one speaker (the longer part's), one text,
    one time slot. Its translations are cleared: a merged line needs fresh ones."""
    rows = db.rows("SELECT * FROM sentences WHERE project_id=? ORDER BY start", pid)
    i = next((k for k, r in enumerate(rows) if r["id"] == sid), None)
    if i is None or i + 1 >= len(rows):
        raise ValueError("no following line to merge with")
    a, b = rows[i], rows[i + 1]
    speaker = a["speaker"] if (a["end"] - a["start"]) >= (b["end"] - b["start"]) else b["speaker"]
    db.run("DELETE FROM translations WHERE project_id=? AND sentence_id IN (?,?)", pid, a["id"], b["id"])
    db.run("UPDATE sentences SET speaker=?, end=?, text=?, words=?, reviewed=0"
           " WHERE project_id=? AND id=?", speaker, max(a["end"], b["end"]),
           f"{a['text'].rstrip()} {b['text'].lstrip()}".strip(),
           json.dumps(_words(pid, a) + _words(pid, b)), pid, a["id"])
    db.run("DELETE FROM sentences WHERE project_id=? AND id=?", pid, b["id"])
    chaps.normalize(pid)  # merging across a chapter start moves it to the next line
    return {"kept": a["id"], "removed": b["id"]}


def split(pid: str, sid: int, word_index: int) -> dict:
    """Cut a line before its ``word_index``-th word (counting the words of the text
    as shown). Times come from the word timings when they still match the text;
    otherwise the slot is divided in proportion to the text."""
    s = db.row("SELECT * FROM sentences WHERE project_id=? AND id=?", pid, sid)
    if not s:
        raise ValueError("no such line")
    tokens = s["text"].split()
    if not 0 < word_index < len(tokens):
        raise ValueError("the split point must be between two words")
    words = _words(pid, s)
    if len(words) == len(tokens):
        cut_end, cut_start = words[word_index - 1]["end"], words[word_index]["start"]
        w1, w2 = words[:word_index], words[word_index:]
    else:
        frac = len(" ".join(tokens[:word_index])) / max(1, len(s["text"]))
        cut_end = cut_start = round(s["start"] + frac * (s["end"] - s["start"]), 3)
        w1, w2 = [], []
    new_id = (db.row("SELECT MAX(id) m FROM sentences WHERE project_id=?", pid)["m"] or 0) + 1
    db.run("DELETE FROM translations WHERE project_id=? AND sentence_id=?", pid, sid)
    db.run("UPDATE sentences SET end=?, text=?, words=?, reviewed=0"
           " WHERE project_id=? AND id=?", cut_end, " ".join(tokens[:word_index]), json.dumps(w1), pid, sid)
    db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text,words) VALUES (?,?,?,?,?,?,?)",
           pid, new_id, s["speaker"], cut_start, s["end"], " ".join(tokens[word_index:]), json.dumps(w2))
    chaps.normalize(pid)
    return {"first": sid, "second": new_id}
