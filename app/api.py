"""HTTP API for the desktop UI. Bound to 127.0.0.1 only (see main.py)."""
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import aligners, banks, buckets, bulk, cast, chapters, db, feeds, langs, libraries, library, mix, package, project, recurring, runs, series, settings, tasks, voice

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
    bucket: str | None = None           # kind "bucket": namespace/name on Hugging Face


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
    """Brief rows for lists (library videos are explored per library); the open project's
    full summary is GET /api/projects/{pid}."""
    return project.briefs()


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
    return [{"kind": k, "label": v[0], "unit": v[1]} for k, v in series.KINDS.items() if k != "single"]


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
    remote: bool = False  # only register them: a remote worker fetches them (nothing downloads here)


@app.post("/api/series/{sid}/feed/add")
def add_from_feed(sid: str, body: FeedPick):
    """Add the picked videos in order; their downloads run one at a time."""
    _s(sid)
    if body.remote:
        return bulk.add(sid, body.items, (body.clip_start, body.clip_end))
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


# ---- whole-channel runs on Colab (app/bulk.py) -----------------------------------------------
class BulkReq(BaseModel):
    root: str = "colab"
    batch: int = bulk.BATCH
    height: int = 720


@app.get("/api/series/{sid}/bulk")
def bulk_status(sid: str):
    _s(sid)
    return bulk.status(sid)


@app.post("/api/series/{sid}/bulk")
def bulk_queue(sid: str, body: BulkReq):
    """Queue every video of the series that has no lines yet, in batches, on a remote worker."""
    _s(sid)
    try:
        return bulk.queue(sid, body.root, max(1, min(body.batch, 100)), body.height)
    except (KeyError, OSError) as e:
        raise HTTPException(409, f"job folder not reachable: {e}")


@app.post("/api/series/{sid}/bulk/load")
def bulk_load(sid: str):
    """Load finished videos: lines and speakers here, video and audio stay on Drive."""
    _s(sid)
    return bulk.load(sid)


@app.post("/api/series/{sid}/bulk/retry")
def bulk_retry(sid: str):
    _s(sid)
    return bulk.retry_failed(sid)


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
    path = {"video": p["video"], "audio": p["audio"], "vocals": project.stem(pid, "vocals"),
            "background": project.stem(pid, "background")}.get(name)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"{name} not available")
    return FileResponse(path)


# ---- characters --------------------------------------------------------------------------
_energy_cache: dict[str, tuple[float, np.ndarray]] = {}


def _energy(pid: str) -> np.ndarray | None:
    """RMS of the vocal stem in 50 ms frames, decoded once and cached per file mtime."""
    f = project.stem(pid, "vocals")
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


def _rebank(*uids: str | None) -> None:
    """A character's episodes changed: its voice bank follows (new lines cut, old dropped)."""
    for uid in {u for u in uids if u}:
        try:
            banks.rebuild(uid)
        except (KeyError, OSError, subprocess.CalledProcessError):
            pass  # a bank is rebuilt on demand when voicing too


@app.post("/api/projects/{pid}/characters/{label}/confirm")
def confirm_character(pid: str, label: str):
    try:
        a = cast.confirm(pid, label)
    except KeyError:
        raise HTTPException(404, "no such speaker")
    _rebank(a["character_uid"])
    return a


@app.post("/api/projects/{pid}/characters/{label}/link")
def link_character(pid: str, label: str, body: LinkReq):
    """Say who this voice is: a character of the work, or (none) a character of its own."""
    before = cast.character_of(pid, label)
    try:
        a = cast.link(pid, label, body.character_uid) if body.character_uid else cast.detach(pid, label)
    except KeyError:
        raise HTTPException(404, "no such speaker or character")
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebank(a["character_uid"], before and db.row("SELECT uid FROM cast WHERE uid=?", before["uid"]) and before["uid"])
    return a


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
        c = cast.merge(uid, body.into)
    except KeyError:
        raise HTTPException(404, "no such character")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.run("DELETE FROM cast_bank WHERE character_uid=?", uid)
    _rebank(body.into)
    return c


@app.get("/api/cast/{uid}/bank")
def cast_bank(uid: str):
    """The character's voice bank, held-out and excluded lines, and the lines it could use."""
    try:
        cast.get(uid)
    except KeyError:
        raise HTTPException(404, "no such character")
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM projects")}
    used = {(r["source_id"], r["line_id"]) for r in banks.rows(uid)}
    return {"rows": [r | {"source_name": names.get(r["source_id"])} for r in banks.rows(uid)],
            "candidates": [c | {"source_name": names.get(c["source_id"])} for c in banks.candidates(uid)
                           if (c["source_id"], c["id"]) not in used]}


@app.post("/api/cast/{uid}/bank/rebuild")
def rebuild_bank(uid: str):
    try:
        return banks.rebuild(uid)
    except KeyError:
        raise HTTPException(404, "no such character")


class BankPin(BaseModel):
    source_id: str
    line_id: int
    role: str = "bank"  # bank | heldout | excluded


@app.put("/api/cast/{uid}/bank")
def pin_bank(uid: str, body: BankPin):
    try:
        return banks.pin(uid, body.source_id, body.line_id, body.role)
    except KeyError:
        raise HTTPException(404, "no such character")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/cast/{uid}/bank/{source_id}/{line_id}")
def bank_audio(uid: str, source_id: str, line_id: int):
    r = db.row("SELECT path FROM cast_bank WHERE character_uid=? AND source_id=? AND line_id=?", uid, source_id, line_id)
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404, "not in the bank")
    return FileResponse(r["path"])


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


# ---- sharing a work (docs/PACKAGE.md) ------------------------------------------------------
class ExportReq(BaseModel):
    langs: list[str] | None = None  # none = every target language of the work
    media: str = "opus"             # none | opus | flac
    takes: bool = False
    note: str = ""


@app.post("/api/series/{sid}/export")
def export_work(sid: str, body: ExportReq):
    """Write the work as a .lbwork package another team can import (data/exports/)."""
    _s(sid)
    try:
        f = package.export(sid, body.langs, body.media, body.takes, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"name": f.name, "path": str(f), "size": f.stat().st_size}


def _export_file(name: str) -> Path:
    f = db.DATA / "exports" / Path(name).name  # a bare file name: never a path out of the folder
    if f.suffix != ".lbwork" or not f.exists():
        raise HTTPException(404, "no such package")
    return f


@app.get("/api/exports/{name}")
def download_export(name: str):
    return FileResponse(_export_file(name), filename=Path(name).name, media_type="application/zip")


@app.post("/api/exports/open")
def open_exports():
    """Show the packages folder in Explorer (this app only ever runs on the user's PC)."""
    d = db.DATA / "exports"
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(d)  # noqa: S606 - local desktop action on the app's own folder
    return {"ok": True}


class PackagePath(BaseModel):
    path: str
    fetch: bool = True  # fetch missing video/stems from the origin


def _package_path(p: str) -> Path:
    f = Path(p.strip().strip('"'))
    if f.suffix.lower() != ".lbwork" or not f.is_file():
        raise HTTPException(400, "give the path of a .lbwork file on this PC")
    return f


@app.post("/api/import/inspect")
def inspect_package(body: PackagePath):
    try:
        return package.inspect(_package_path(body.path))
    except (ValueError, KeyError, zipfile.BadZipFile) as e:
        raise HTTPException(400, f"not a readable work package: {e}")


@app.post("/api/import")
def import_package(body: PackagePath):
    """Bring a shared work in (new, or adding to the same work already here)."""
    try:
        return package.import_work(_package_path(body.path), fetch=body.fetch)
    except (ValueError, KeyError, zipfile.BadZipFile) as e:
        raise HTTPException(400, f"could not import: {e}")


# ---- library folders (app/libraries.py) ------------------------------------------------------
class NewLibrary(BaseModel):
    name: str
    root: str               # the device that runs it: a job folder id ("colab", "local", …)
    path: str               # the folder as this PC sees it (G:\My Drive\…, E:\…)
    src_lang: str = "en"
    targets: list[str] = ["am"]
    kind: str = "other"


def _lib(lid: str) -> dict:
    try:
        return libraries.get(lid)
    except KeyError:
        raise HTTPException(404, "no such library")


@app.get("/api/libraries")
def list_libraries():
    return libraries.listing()


@app.post("/api/libraries")
def new_library(body: NewLibrary):
    try:
        return libraries.create(body.name, body.root, body.path, body.src_lang, body.targets, body.kind)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/libraries/{lid}/scan")
def scan_library(lid: str):
    """Catalogue new videos (names only; nothing is read or copied)."""
    _lib(lid)
    try:
        return libraries.scan(lid)
    except OSError as e:
        raise HTTPException(409, f"the folder is not reachable: {e}")


@app.get("/api/libraries/{lid}")
def library_tree(lid: str):
    return _lib(lid) | {"works": libraries.tree(lid)}


class Only(BaseModel):
    only: list[str] | None = None


@app.post("/api/libraries/{lid}/load_subtitles")
def library_subtitles(lid: str, body: Only):
    _lib(lid)
    return libraries.load_subtitles(lid, body.only)


# ---- runs (app/runs.py) ------------------------------------------------------------------------
class RunReq(BaseModel):
    videos: list[str]                   # project ids, from one work or many
    root: str                           # the device: a job folder id
    stages: list[str] | None = None     # which stages, in pipeline order (None = all)
    options: dict = {}
    name: str = "run"
    owner: str | None = None            # "series:<id>" or "library:<id>" (where it is listed)


@app.post("/api/runs")
def new_run(body: RunReq):
    if not body.videos:
        raise HTTPException(400, "choose at least one video")
    try:
        return runs.create_for(body.videos, body.root, body.stages, body.options, body.name, body.owner)
    except (ValueError, KeyError, OSError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/runs")
def list_runs(owner: str):
    return runs.listing(owner)


def _known_root(rid: str) -> None:
    if rid not in {r["id"] for r in settings.load()["roots"]}:  # settings.root() would fall back to another device
        raise HTTPException(404, f"no device '{rid}'")


@app.get("/api/roots/{rid}/runs")
def root_runs(rid: str):
    """Every run in a device's folder (a notebook's too), with progress; new results open by themselves."""
    _known_root(rid)
    try:
        return {"runs": runs.scan(rid), "last_sync": buckets.last_sync(rid),
                "syncing": tasks.busy(f"root:{rid}", "sync bucket")}
    except (KeyError, OSError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/roots/{rid}/sync")
def root_sync(rid: str):
    """Pull a Hugging Face bucket device into its folder (in the background)."""
    _known_root(rid)
    if settings.root(rid).get("kind") != "bucket":
        raise HTTPException(400, "not a Hugging Face bucket")
    return {"task": tasks.start(f"root:{rid}", "sync bucket", buckets.sync, rid, serial=f"sync-{rid}")}


@app.post("/api/runs/{root}/{run_id}/open")
def open_run(root: str, run_id: str):
    """Bring a run's results in (media stay on the device)."""
    try:
        return runs.open_results(root, run_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


# ---- static UI ---------------------------------------------------------------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
