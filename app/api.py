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

from . import aligners, db, mix, project, settings, tasks, voice

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
    return project.create(body.name.strip() or "Untitled", body.source, body.clip_start,
                          body.clip_end, body.max_speakers, body.src_lang, body.tgt_lang)


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
    chars = db.rows("SELECT * FROM characters WHERE project_id=? ORDER BY talk_s DESC", pid)
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


@app.patch("/api/projects/{pid}/characters/{label}")
def patch_character(pid: str, label: str, body: CharPatch):
    for k, v in body.model_dump(exclude_none=True).items():
        db.run(f"UPDATE characters SET {k}=? WHERE project_id=? AND label=?", int(v) if isinstance(v, bool) else v,
               pid, label)
    return db.row("SELECT * FROM characters WHERE project_id=? AND label=?", pid, label)


class Merge(BaseModel):
    source: str
    into: str


@app.post("/api/projects/{pid}/characters/merge")
def merge_characters(pid: str, body: Merge):
    """Two clusters are one person: move every line and add up talk time."""
    a = db.row("SELECT * FROM characters WHERE project_id=? AND label=?", pid, body.source)
    b = db.row("SELECT * FROM characters WHERE project_id=? AND label=?", pid, body.into)
    if not a or not b or a == b:
        raise HTTPException(400, "bad merge")
    db.run("UPDATE sentences SET speaker=? WHERE project_id=? AND speaker=?", body.into, pid, body.source)
    db.run("UPDATE characters SET talk_s=talk_s+? WHERE project_id=? AND label=?", a["talk_s"], pid, body.into)
    db.run("DELETE FROM characters WHERE project_id=? AND label=?", pid, body.source)
    return {"ok": True}


# ---- transcript / translation ------------------------------------------------------------
@app.get("/api/projects/{pid}/sentences")
def sentences(pid: str):
    _p(pid)
    return project.sentences(pid)


class SentPatch(BaseModel):
    text: str | None = None
    speaker: str | None = None
    am: str | None = None
    am_locked: bool | None = None
    chapter_break: bool | None = None
    reviewed: bool | None = None
    mode: str | None = None  # "dub" | "keep" | "auto" (back to the suggestion)


@app.patch("/api/projects/{pid}/sentences/{sid}")
def patch_sentence(pid: str, sid: int, body: SentPatch):
    changes = body.model_dump(exclude_none=True)
    if "mode" in changes:
        if changes["mode"] not in ("dub", "keep", "auto"):
            raise HTTPException(400, "mode must be dub, keep or auto")
        if changes["mode"] == "auto":
            changes["mode"] = None
            db.run("UPDATE sentences SET mode=NULL WHERE project_id=? AND id=?", pid, sid)
            changes.pop("mode")
    if "am" in changes and "am_locked" not in changes:
        changes["am_locked"] = True  # a hand edit is never overwritten by re-translation
    for k, v in changes.items():
        db.run(f"UPDATE sentences SET {k}=? WHERE project_id=? AND id=?", int(v) if isinstance(v, bool) else v, pid, sid)
    return next(s for s in project.sentences(pid) if s["id"] == sid)


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


class TranslateReq(BaseModel):
    chapter: int | None = None
    force: bool = False


@app.post("/api/projects/{pid}/translate")
def translate(pid: str, body: TranslateReq):
    _p(pid)
    if tasks.busy(pid, "translate"):
        raise HTTPException(409, "translation already running")
    return {"task": project.translate(pid, body.chapter, body.force)}


# ---- voice -------------------------------------------------------------------------------
class VoiceReq(BaseModel):
    root: str | None = None
    ids: list[int] | None = None
    takes: int | None = None


@app.post("/api/projects/{pid}/voice")
def voice_queue(pid: str, body: VoiceReq):
    _p(pid)
    try:
        return voice.queue(pid, body.root, body.ids, body.takes)
    except (RuntimeError, OSError) as e:
        raise HTTPException(409, str(e))


@app.get("/api/projects/{pid}/voice")
def voice_state(pid: str):
    """Lines with their takes; loads any newly finished voice jobs first."""
    _p(pid)
    try:
        voice.ingest(pid)
    except OSError:
        pass  # a job folder may be offline; show what is loaded
    takes: dict[int, list] = {}
    for t in voice.lines_takes(pid):
        takes.setdefault(t["sentence_id"], []).append(t)
    lines = project.sentences(pid)
    for s in lines:
        s["takes"] = [t | {"stale": t["text"] != s["am"]} for t in takes.get(s["id"], [])]
    jobs = [j for j in project.jobs(pid) if j["stage"] == "voice"]
    return {"lines": lines, "jobs": jobs, "engine": voice.ENGINE, "am_rate": db.meta(pid).get("am_rate")}


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
def mix_state(pid: str):
    _p(pid)
    d = mix.mix_dir(pid)
    fitp = d / "fit.json"
    summary = json.loads(fitp.read_text(encoding="utf-8")) if fitp.exists() else None
    meta = db.meta(pid)
    exp = meta.get("exported")
    return {"params": mix.params(pid), "defaults": mix.DEFAULTS, "summary": summary,
            "has_mix": (d / "mix.wav").exists(), "mix_mtime": (d / "mix.wav").stat().st_mtime if (d / "mix.wav").exists() else None,
            "export": {"mp4": exp, "at": meta.get("exported_at")} if exp and Path(exp).exists() else None,
            "tasks": [t for t in tasks.list_for(pid) if t["kind"] in ("mix", "export")][:4]}


@app.put("/api/projects/{pid}/mix/params")
def mix_params(pid: str, body: dict):
    _p(pid)
    return mix.set_params(pid, body)


@app.post("/api/projects/{pid}/mix/render")
def mix_render(pid: str):
    _p(pid)
    if tasks.busy(pid, "mix"):
        raise HTTPException(409, "already rendering")
    return {"task": tasks.start(pid, "mix", lambda update: mix.render(pid, update))}


@app.post("/api/projects/{pid}/mix/export")
def mix_export(pid: str):
    _p(pid)
    if tasks.busy(pid, "export"):
        raise HTTPException(409, "already exporting")
    return {"task": tasks.start(pid, "export", lambda update: mix.export(pid, update))}


@app.get("/api/projects/{pid}/mix/audio/{name}")
def mix_audio(pid: str, name: str):
    f = mix.mix_dir(pid) / f"{name}.wav"
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
