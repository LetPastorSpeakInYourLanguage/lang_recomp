"""HTTP API for the desktop UI. Bound to 127.0.0.1 only (see main.py)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import aligners, cast, chapters, db, feeds, langs, library, mix, project, recurring, series, settings, tasks, voice

app = FastAPI(title="Lang-Bridge")
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"


def _p(pid: str) -> dict:
    try:
        return project.get(pid)
    except KeyError:
        raise HTTPException(404, f"no project {pid}")


# ---- shell -------------------------------------------------------------------------------
def _roots() -> list[dict]:
    """Every configured job folder with reachability and its workers."""
    s = settings.load()
    out = []
    for r in s["roots"]:
        try:
            q = project.queue(r["id"])
            workers = [w for w in q.workers() if w["age_s"] < 86400]  # hide long-dead sessions
            ok = True
        except OSError:
            workers, ok = [], False
        out.append(r | {"active": r["id"] == s["active"], "reachable": ok, "workers": workers,
                        "online": any(w["online"] for w in workers)})
    return out


@app.get("/api/state")
def state():
    roots = _roots()
    active = next(r for r in roots if r["active"])
    return {"roots": roots, "active": active["id"], "drive": active["reachable"], "root": active["path"],
            "workers": active["workers"], "tasks": [t for t in tasks.list_for() if t["state"] == "running"]}


@app.get("/api/settings")
def get_settings():
    return settings.load()


class RootIn(BaseModel):
    id: str | None = None
    name: str
    kind: str
    path: str


class SettingsIn(BaseModel):
    roots: list[RootIn]
    active: str
    aligners: dict[str, str] | None = None
    keep_words: list[str] | None = None


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    try:
        out = settings.save(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    project._queues.clear()  # paths may have changed
    return out


@app.get("/api/aligners/search")
def aligner_search(language: str, q: str = ""):
    try:
        return aligners.search(language.strip().lower(), q.strip())
    except Exception as e:  # network trouble reaches the UI as a message, not a 500
        raise HTTPException(502, f"Hugging Face search failed: {e}")


@app.get("/api/aligners/check")
def aligner_check(repo: str, language: str, sample: str = ""):
    try:
        return aligners.check(repo.strip(), language.strip().lower(), sample or None)
    except Exception as e:
        raise HTTPException(502, f"Hugging Face check failed: {e}")


# ---- projects ----------------------------------------------------------------------------
class NewProject(BaseModel):
    name: str
    source: str
    clip_start: float | None = None
    clip_end: float | None = None
    max_speakers: int | None = None
    src_lang: str = "en"
    tgt_lang: str = "am"


@app.get("/api/projects")
def list_projects():
    return [project.summary(p["id"]) for p in db.rows("SELECT id FROM projects ORDER BY created DESC")]


@app.post("/api/projects")
def new_project(body: NewProject):
    if not body.source.strip():
        raise HTTPException(400, "source is required")
    try:
        return project.create(body.name.strip() or "Untitled", body.source, body.clip_start,
                              body.clip_end, body.max_speakers, body.src_lang, body.tgt_lang)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- series ------------------------------------------------------------------------------
def _s(sid: str) -> dict:
    try:
        return series.get(sid)
    except KeyError:
        raise HTTPException(404, "no such series")


class NewSeries(BaseModel):
    name: str
    kind: str = "other"
    src_lang: str = "en"
    targets: list[str] = ["am"]
    feed_url: str | None = None
    settings: dict = {}


class SeriesPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    src_lang: str | None = None
    targets: list[str] | None = None
    feed_url: str | None = None
    settings: dict | None = None


class NewSource(BaseModel):
    name: str
    source: str
    clip_start: float | None = None
    clip_end: float | None = None
    max_speakers: int | None = None
    origin_id: str | None = None
    published: str | None = None


@app.get("/api/series/kinds")
def series_kinds():
    return [{"kind": k, "label": v[0], "unit": v[1]} for k, v in series.KINDS.items()]


@app.get("/api/series")
def list_series():
    return series.listing()


@app.post("/api/series")
def new_series(body: NewSeries):
    if not body.name.strip():
        raise HTTPException(400, "a series needs a name")
    try:
        return series.create(body.name, body.kind, body.src_lang, body.targets, body.feed_url, body.settings)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/series/{sid}")
def get_series(sid: str):
    return _s(sid) | {"sources": series.sources(sid)}


@app.patch("/api/series/{sid}")
def patch_series(sid: str, body: SeriesPatch):
    _s(sid)
    try:
        return series.update(sid, **body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/series/{sid}/sources")
def new_source(sid: str, body: NewSource):
    _s(sid)
    if not body.source.strip():
        raise HTTPException(400, "source is required")
    try:
        return series.add_source(sid, body.name.strip() or "Untitled", body.source.strip(), body.clip_start,
                                 body.clip_end, body.max_speakers, body.origin_id, body.published)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/series/{sid}")
def delete_series(sid: str):
    """Removes the grouping only; every source stays, as a standalone video."""
    _s(sid)
    return {"released": series.remove(sid)}


@app.get("/api/series/{sid}/feed")
def series_feed(sid: str, limit: int = 100):
    """The channel/playlist's videos (listing only), each marked if already in the series."""
    s = _s(sid)
    if not s["feed_url"]:
        raise HTTPException(400, "set the series' channel or playlist link first")
    try:
        got = feeds.listing(s["feed_url"], max(1, min(limit, 500)))
    except Exception as e:
        raise HTTPException(502, str(e))
    have = {r["origin_id"] for r in db.rows("SELECT origin_id FROM projects WHERE series_id=?", sid)}
    for e in got["entries"]:
        e["added"] = e["id"] in have
    return got


class FeedPick(BaseModel):
    items: list[dict]  # entries from the feed: {id, title, url}
    clip_start: float | None = None
    clip_end: float | None = None


@app.post("/api/series/{sid}/feed/add")
def add_from_feed(sid: str, body: FeedPick):
    """Add the picked videos in order; their downloads run one at a time."""
    _s(sid)
    added, skipped = [], []
    for it in body.items:
        try:
            p = series.add_source(sid, (it.get("title") or it["id"])[:120], it.get("url") or it["id"],
                                  body.clip_start, body.clip_end, origin_id=it["id"])
            added.append(p["id"])
        except (ValueError, KeyError) as e:
            skipped.append({"id": it.get("id"), "reason": str(e)})
    return {"added": added, "skipped": skipped}


# ---- library: clips and collections --------------------------------------------------------
def _clip(cid: int) -> dict:
    try:
        return library.get_clip(cid)
    except KeyError:
        raise HTTPException(404, "no such clip")


def _coll(cid: int) -> dict:
    try:
        return library.get_collection(cid)
    except KeyError:
        raise HTTPException(404, "no such collection")


class NewClip(BaseModel):
    source_id: str
    title: str
    kind: str = "clip"
    note: str = ""
    # the span: two line ids, a whole chapter, or explicit times
    first_line: int | None = None
    last_line: int | None = None
    chapter_id: int | None = None
    start: float | None = None
    end: float | None = None


class ClipPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    note: str | None = None


class Segments(BaseModel):
    segments: list[dict]


class Memberships(BaseModel):
    collection_ids: list[int]


class Named(BaseModel):
    name: str


@app.get("/api/clips/kinds")
def clip_kinds():
    return {"kinds": list(library.KINDS), "recurring": sorted(library.RECURRING)}


@app.get("/api/clips")
def list_clips(series: str | None = None, source: str | None = None, collection: int | None = None,
               kind: str | None = None, deleted: bool = False, lang: str | None = None):
    """Clips, each with its source's name and the languages whose mix is rendered (so
    the clip can be played dubbed, as a slice of that mix)."""
    out, seen = library.clips(series, source, collection, kind, deleted, lang), {}
    for c in out:
        pid = c["source_id"]
        if pid not in seen:
            p = db.row("SELECT name FROM projects WHERE id=?", pid)
            seen[pid] = {"name": p["name"] if p else pid,
                         "mixed": {t: (mix.mix_dir(pid, t) / "mix.wav").stat().st_mtime for t in project.targets(pid)
                                   if (mix.mix_dir(pid, t) / "mix.wav").exists()} if p else {}}
        c["source_name"], c["mixed"] = seen[pid]["name"], seen[pid]["mixed"]
        if c["recurring"]:
            c["occurrences"] = {st: 0 for st in recurring.STATUSES}
            for o in recurring.occurrences(c["id"]):
                c["occurrences"][o["status"]] += 1
    return out


@app.post("/api/clips")
def new_clip(body: NewClip):
    _p(body.source_id)
    try:
        if body.first_line is not None:
            start, end = library.span_of_lines(body.source_id, body.first_line, body.last_line or body.first_line)
        elif body.chapter_id is not None:
            start, end = library.chapter_span(body.source_id, body.chapter_id)
        elif body.start is not None and body.end is not None:
            start, end = body.start, body.end
        else:
            raise ValueError("give the clip's lines, chapter or times")
        return library.create_clip(body.source_id, start, end, body.title, body.kind, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/clips/{cid}")
def get_clip(cid: int, rev: int | None = None, lang: str | None = None):
    _clip(cid)
    try:
        c = library.get_clip(cid, rev)
    except KeyError:
        raise HTTPException(404, "no such revision")
    return c | {"lines": library.clip_lines(c, lang)}


@app.patch("/api/clips/{cid}")
def patch_clip(cid: int, body: ClipPatch):
    _clip(cid)
    try:
        return library.update_clip(cid, body.title, body.kind, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clips/{cid}/revisions")
def revise_clip(cid: int, body: Segments):
    _clip(cid)
    try:
        return library.revise_clip(cid, body.segments)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/clips/{cid}")
def delete_clip(cid: int):
    _clip(cid)
    return library.remove_clip(cid)


@app.post("/api/clips/{cid}/restore")
def restore_clip(cid: int):
    _clip(cid)
    return library.remove_clip(cid, restore=True)


@app.put("/api/clips/{cid}/collections")
def clip_collections(cid: int, body: Memberships):
    _clip(cid)
    try:
        return {"collection_ids": library.set_memberships("clip", cid, body.collection_ids)}
    except KeyError:
        raise HTTPException(404, "no such collection")


@app.post("/api/clips/{cid}/search")
def search_clip(cid: int):
    """Find a recurring clip in its series by audio; new hits are proposed."""
    _clip(cid)
    try:
        return recurring.search(cid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/clips/{cid}/occurrences")
def clip_occurrences(cid: int):
    _clip(cid)
    return recurring.occurrences(cid)


@app.post("/api/clips/{cid}/occurrences/confirm_all")
def confirm_occurrences(cid: int):
    _clip(cid)
    return {"confirmed": recurring.confirm_all(cid)}


class OccurrencePatch(BaseModel):
    status: str


@app.patch("/api/occurrences/{oid}")
def patch_occurrence(oid: int, body: OccurrencePatch):
    try:
        return recurring.set_status(oid, body.status)
    except KeyError:
        raise HTTPException(404, "no such occurrence")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/collections")
def list_collections(deleted: bool = False):
    return library.collections(deleted)


@app.post("/api/collections")
def new_collection(body: Named):
    try:
        return library.create_collection(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/collections/{cid}")
def rename_collection(cid: int, body: Named):
    _coll(cid)
    try:
        return library.rename_collection(cid, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/collections/{cid}")
def archive_collection(cid: int):
    """Archives the folder; its clips stay."""
    _coll(cid)
    return library.archive_collection(cid)


@app.post("/api/collections/{cid}/restore")
def restore_collection(cid: int):
    _coll(cid)
    return library.archive_collection(cid, restore=True)


@app.get("/api/series/{sid}/discover")
def discover_parts(sid: str, min_s: float = 8.0):
    """Stretches of sound the series' sources share: candidate intros and other
    recurring parts. Nothing is stored until one is saved as a clip."""
    _s(sid)
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM projects WHERE series_id=?", sid)}
    out = recurring.discover(sid, max(4.0, min_s))
    for c in out:
        c["origin"]["source_name"] = names.get(c["origin"]["source_id"])
        for m in c["members"]:
            m["source_name"] = names.get(m["source_id"])
    return out


class Order(BaseModel):
    ids: list[str]


@app.put("/api/series/{sid}/order")
def order_series(sid: str, body: Order):
    _s(sid)
    return series.reorder(sid, body.ids)


class Attach(BaseModel):
    series_id: str | None = None  # none = standalone


@app.put("/api/projects/{pid}/series")
def attach_project(pid: str, body: Attach):
    _p(pid)
    if body.series_id:
        _s(body.series_id)
    return series.attach(pid, body.series_id)


@app.post("/api/projects/{pid}/import")
def retry_import(pid: str):
    """Try a failed download/import again."""
    _p(pid)
    try:
        return {"task": project.retry_import(pid)}
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    _p(pid)
    return project.summary(pid)


class AnalyzeReq(BaseModel):
    root: str | None = None


@app.post("/api/projects/{pid}/analyze")
def analyze(pid: str, body: AnalyzeReq | None = None):
    _p(pid)
    try:
        return project.analyze(pid, body.root if body else None)
    except OSError as e:
        raise HTTPException(409, f"job folder not reachable: {e}")


@app.post("/api/projects/{pid}/realign")
def realign(pid: str, body: AnalyzeReq | None = None):
    _p(pid)
    try:
        return project.realign(pid, body.root if body else None)
    except (RuntimeError, OSError) as e:
        raise HTTPException(409, str(e))


@app.post("/api/projects/{pid}/ingest")
def ingest(pid: str):
    _p(pid)
    try:
        return project.ingest(pid)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/projects/{pid}/jobs")
def jobs(pid: str):
    _p(pid)
    return {"colab": project.jobs(pid), "local": tasks.list_for(pid)}


@app.get("/api/projects/{pid}/jobs/{jid}/log")
def job_log(pid: str, jid: str):
    j = db.row("SELECT * FROM jobs WHERE id=?", jid)
    if not j:
        raise HTTPException(404, "no such job")
    return {"log": project.job_queue(j).log(jid)}


# ---- media -------------------------------------------------------------------------------
@app.get("/api/projects/{pid}/media/{name}")
def media(pid: str, name: str):
    p = _p(pid)
    d = project.pdir(pid)
    path = {"video": p["video"], "audio": p["audio"], "vocals": d / "vocals.flac",
            "background": d / "background.flac"}.get(name)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"{name} not available")
    return FileResponse(path)


# ---- characters --------------------------------------------------------------------------
_energy_cache: dict[str, tuple[float, np.ndarray]] = {}


def _energy(pid: str) -> np.ndarray | None:
    """RMS of the vocal stem in 50 ms frames, decoded once and cached per file mtime."""
    f = project.pdir(pid) / "vocals.flac"
    if not f.exists():
        return None
    mt = f.stat().st_mtime
    hit = _energy_cache.get(pid)
    if hit and hit[0] == mt:
        return hit[1]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    n = len(x) // 800
    rms = np.sqrt((x[: n * 800].reshape(n, 800) ** 2).mean(1) + 1e-12)
    _energy_cache[pid] = (mt, rms)
    return rms


@app.get("/api/projects/{pid}/characters")
def characters(pid: str):
    _p(pid)
    chars = cast.for_source(pid)
    for c in chars:  # a proposed link shows who the voice sounds like, and the other options
        c["matches"] = cast.matches(pid, c["label"])[:4]
    sents = project.sentences(pid)
    rms = _energy(pid)
    for c in chars:
        mine = [s for s in sents if s["speaker"] == c["label"]]
        c["sentences"] = len(mine)
        # Tone samples: the speaker's lines spread from their quietest to their most
        # animated delivery (vocal-stem loudness), so you hear their range, not one take.
        # Only clean lines (capitalised, sentence-final punctuation): unpunctuated
        # stretches are where the speaker boundary may have slipped by a word.
        ok = [s for s in mine if 1.2 <= s["slot_s"] <= 9]
        clean = [s for s in ok if s["text"][:1].isupper() and s["text"].rstrip()[-1:] in ".?!"]
        cand = clean if len(clean) >= 3 else ok
        if rms is not None and cand:
            for s in cand:
                seg = rms[int(s["start"] * 20):max(int(s["start"] * 20) + 1, int(s["end"] * 20))]
                s["energy_db"] = round(float(20 * np.log10(np.percentile(seg, 90) + 1e-9)), 1)
            cand.sort(key=lambda s: s["energy_db"])
            k = min(5, len(cand))
            picks = [cand[round(i * (len(cand) - 1) / max(1, k - 1))] for i in range(k)]
        else:
            picks = cand[:5]
        c["samples"] = [{"id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"],
                         "energy_db": s.get("energy_db")} for s in picks]
    return chars


class CharPatch(BaseModel):
    name: str | None = None
    gender: str | None = None
    important: bool | None = None
    role: str | None = None
    notes: str | None = None


@app.patch("/api/projects/{pid}/characters/{label}")
def patch_character(pid: str, label: str, body: CharPatch):
    """Edits the character this voice is: the change holds in every source it appears in."""
    c = cast.character_of(pid, label)
    if not c:
        raise HTTPException(404, "no such speaker")
    return cast.update(c["uid"], **body.model_dump(exclude_none=True))


class LinkReq(BaseModel):
    character_uid: str | None = None  # none = a character of its own


@app.post("/api/projects/{pid}/characters/{label}/confirm")
def confirm_character(pid: str, label: str):
    try:
        return cast.confirm(pid, label)
    except KeyError:
        raise HTTPException(404, "no such speaker")


@app.post("/api/projects/{pid}/characters/{label}/link")
def link_character(pid: str, label: str, body: LinkReq):
    """Say who this voice is: a character of the work, or (none) a character of its own."""
    try:
        return cast.link(pid, label, body.character_uid) if body.character_uid else cast.detach(pid, label)
    except KeyError:
        raise HTTPException(404, "no such speaker or character")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/series/{sid}/cast")
def work_cast(sid: str):
    _s(sid)
    return cast.of_work(sid)


@app.patch("/api/cast/{uid}")
def patch_cast(uid: str, body: CharPatch):
    try:
        return cast.update(uid, **body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(404, "no such character")


class CastName(BaseModel):
    name: str


@app.put("/api/cast/{uid}/names/{lang}")
def cast_name(uid: str, lang: str, body: CastName):
    try:
        return cast.set_name(uid, project.check_lang(lang), body.name)
    except KeyError:
        raise HTTPException(404, "no such character")
    except ValueError as e:
        raise HTTPException(400, str(e))


class CastMerge(BaseModel):
    into: str


@app.post("/api/cast/{uid}/merge")
def merge_cast(uid: str, body: CastMerge):
    """Two characters of a work are one person."""
    try:
        return cast.merge(uid, body.into)
    except KeyError:
        raise HTTPException(404, "no such character")
    except ValueError as e:
        raise HTTPException(400, str(e))


class Merge(BaseModel):
    source: str
    into: str


@app.post("/api/projects/{pid}/characters/merge")
def merge_characters(pid: str, body: Merge):
    """Two clusters are one voice in this source: move every line and add up talk time."""
    if body.source == body.into:
        raise HTTPException(400, "bad merge")
    try:
        cast.merge_labels(pid, body.source, body.into)
    except KeyError:
        raise HTTPException(400, "bad merge")
    return {"ok": True}


# ---- languages ---------------------------------------------------------------------------
@app.get("/api/languages")
def languages():
    return langs.catalogue()


class LangReq(BaseModel):
    lang: str


@app.post("/api/projects/{pid}/languages")
def add_language(pid: str, body: LangReq):
    _p(pid)
    try:
        return {"targets": project.add_target(pid, body.lang)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- transcript / translation ------------------------------------------------------------
@app.get("/api/projects/{pid}/sentences")
def sentences(pid: str, lang: str | None = None):
    _p(pid)
    return project.sentences(pid, lang)


class SentPatch(BaseModel):
    text: str | None = None
    speaker: str | None = None
    reviewed: bool | None = None
    mode: str | None = None  # "dub" | "keep" | "auto" (back to the suggestion)
    # the translation into `lang` (default: the primary target language)
    lang: str | None = None
    tr: str | None = None
    tr_locked: bool | None = None


LINE_FIELDS = ("text", "speaker", "reviewed", "mode")


@app.patch("/api/projects/{pid}/sentences/{sid}")
def patch_sentence(pid: str, sid: int, body: SentPatch):
    _p(pid)
    changes = body.model_dump(exclude_none=True)
    lang = project.lang_or_primary(pid, changes.pop("lang", None))
    if "mode" in changes:
        if changes["mode"] not in ("dub", "keep", "auto"):
            raise HTTPException(400, "mode must be dub, keep or auto")
        if changes["mode"] == "auto":
            changes.pop("mode")
            db.run("UPDATE sentences SET mode=NULL WHERE project_id=? AND id=?", pid, sid)
    if "tr" in changes or "tr_locked" in changes:
        text = changes.pop("tr", None)
        # A hand edit locks the line, so re-translating never overwrites it.
        locked = changes.pop("tr_locked", True if text is not None else None)
        project.set_translation(pid, sid, lang, text, locked, provenance="human")
    for k in LINE_FIELDS:
        if k in changes:
            v = changes[k]
            db.run(f"UPDATE sentences SET {k}=? WHERE project_id=? AND id=?", int(v) if isinstance(v, bool) else v, pid, sid)
    return next(x for x in project.sentences(pid, lang) if x["id"] == sid)


@app.post("/api/projects/{pid}/sentences/{sid}/merge_next")
def merge_next(pid: str, sid: int):
    _p(pid)
    try:
        return project.merge_next(pid, sid)
    except ValueError as e:
        raise HTTPException(400, str(e))


class SplitReq(BaseModel):
    word_index: int


@app.post("/api/projects/{pid}/sentences/{sid}/split")
def split_sentence(pid: str, sid: int, body: SplitReq):
    _p(pid)
    try:
        return project.split(pid, sid, body.word_index)
    except ValueError as e:
        raise HTTPException(400, str(e))


class ChapterAt(BaseModel):
    at: int  # line id


class ChapterPatch(BaseModel):
    title: str


@app.get("/api/projects/{pid}/chapters")
def list_chapters(pid: str):
    _p(pid)
    return chapters.listing(pid)


@app.post("/api/projects/{pid}/chapters/toggle")
def toggle_chapter(pid: str, body: ChapterAt):
    """Start a chapter at this line, or fold the chapter it opens into the previous one."""
    _p(pid)
    try:
        return chapters.toggle(pid, body.at)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/projects/{pid}/chapters/{cid}")
def rename_chapter(pid: str, cid: int, body: ChapterPatch):
    _p(pid)
    try:
        chapters.rename(pid, cid, body.title)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return next(c for c in chapters.listing(pid) if c["id"] == cid)


class TranslateReq(BaseModel):
    chapter: int | None = None  # chapter id; none = every chapter
    force: bool = False
    lang: str | None = None


@app.post("/api/projects/{pid}/translate")
def translate(pid: str, body: TranslateReq):
    _p(pid)
    if tasks.busy(pid, "translate"):
        raise HTTPException(409, "translation already running")
    try:
        return {"task": project.translate(pid, body.lang, body.chapter, body.force)}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---- voice -------------------------------------------------------------------------------
class VoiceReq(BaseModel):
    root: str | None = None
    ids: list[int] | None = None
    takes: int | None = None
    lang: str | None = None


@app.post("/api/projects/{pid}/voice")
def voice_queue(pid: str, body: VoiceReq):
    _p(pid)
    try:
        return voice.queue(pid, body.root, body.ids, body.takes, body.lang)
    except (RuntimeError, OSError) as e:
        raise HTTPException(409, str(e))


@app.get("/api/projects/{pid}/voice")
def voice_state(pid: str, lang: str | None = None):
    """Lines with their takes in ``lang``; loads any newly finished voice jobs first."""
    _p(pid)
    lang = project.lang_or_primary(pid, lang)
    try:
        voice.ingest(pid)
    except OSError:
        pass  # a job folder may be offline; show what is loaded
    takes: dict[int, list] = {}
    for t in voice.lines_takes(pid, lang=lang):
        takes.setdefault(t["sentence_id"], []).append(t)
    lines = project.sentences(pid, lang)
    for x in lines:
        x["takes"] = [t | {"stale": t["text"] != x["tr"]} for t in takes.get(x["id"], [])]
    jobs = [j for j in project.jobs(pid) if j["stage"] == "voice"]
    return {"lang": lang, "lines": lines, "jobs": jobs, "engine": voice.ENGINE, "rate": project.rate(pid, lang)}


class ChooseReq(BaseModel):
    take_id: int


@app.post("/api/projects/{pid}/voice/choose")
def voice_choose(pid: str, body: ChooseReq):
    try:
        voice.choose(pid, body.take_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@app.get("/api/projects/{pid}/takes/{take_id}")
def take_audio(pid: str, take_id: int):
    t = db.row("SELECT path FROM takes WHERE rowid=? AND project_id=?", take_id, pid)
    if not t or not Path(t["path"]).exists():
        raise HTTPException(404, "take not found")
    return FileResponse(t["path"], media_type="audio/wav")


# ---- mix & export ------------------------------------------------------------------------
@app.get("/api/projects/{pid}/mix")
def mix_state(pid: str, lang: str | None = None):
    _p(pid)
    lang = project.lang_or_primary(pid, lang)
    d = mix.mix_dir(pid, lang)
    fitp = d / "fit.json"
    summary = json.loads(fitp.read_text(encoding="utf-8")) if fitp.exists() else None
    for line in (summary or {}).get("lines", []):  # renders from before languages were data
        line.setdefault("tr", line.get("am", ""))
        line.setdefault("src", line.get("en", ""))
    meta = db.meta(pid)
    exp = (meta.get("exports") or {}).get(lang)
    if not exp and meta.get("exported") and lang == project.get(pid)["tgt_lang"]:
        exp = {"mp4": meta["exported"], "at": meta.get("exported_at")}
    return {"lang": lang, "params": mix.params(pid), "defaults": mix.DEFAULTS, "summary": summary,
            "has_mix": (d / "mix.wav").exists(), "mix_mtime": (d / "mix.wav").stat().st_mtime if (d / "mix.wav").exists() else None,
            "export": exp if exp and Path(exp["mp4"]).exists() else None,
            "tasks": [t for t in tasks.list_for(pid) if t["kind"] in ("mix", "export")][:4]}


@app.put("/api/projects/{pid}/mix/params")
def mix_params(pid: str, body: dict):
    _p(pid)
    return mix.set_params(pid, body)


class LangOnly(BaseModel):
    lang: str | None = None


@app.post("/api/projects/{pid}/mix/render")
def mix_render(pid: str, body: LangOnly | None = None):
    _p(pid)
    if tasks.busy(pid, "mix"):
        raise HTTPException(409, "already rendering")
    lang = project.lang_or_primary(pid, body.lang if body else None)
    return {"task": tasks.start(pid, "mix", lambda update: mix.render(pid, lang, update))}


@app.post("/api/projects/{pid}/mix/export")
def mix_export(pid: str, body: LangOnly | None = None):
    _p(pid)
    if tasks.busy(pid, "export"):
        raise HTTPException(409, "already exporting")
    lang = project.lang_or_primary(pid, body.lang if body else None)
    return {"task": tasks.start(pid, "export", lambda update: mix.export(pid, lang, update))}


@app.get("/api/projects/{pid}/mix/audio/{name}")
def mix_audio(pid: str, name: str, lang: str | None = None):
    f = mix.mix_dir(pid, lang) / f"{name}.wav"
    if name not in ("mix", "dub") or not f.exists():
        raise HTTPException(404, "not rendered yet")
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/mix/open")
def mix_open(pid: str):
    """Show the export folder in Explorer (this app only ever runs on the user's PC)."""
    d = project.pdir(pid) / "export"
    d.mkdir(exist_ok=True)
    os.startfile(d)  # noqa: S606 - local desktop action on the app's own folder
    return {"ok": True}


# ---- static UI ---------------------------------------------------------------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
