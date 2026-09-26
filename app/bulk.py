"""Whole-channel runs on a remote worker (Colab): nothing is downloaded to this PC.

A series' videos are added as sources without importing them here. They are queued in
batches as ``bulk`` jobs (worker/lb_worker/stages/bulk.py): the worker downloads each
video from its origin into the job folder's library (``library/<work uid>/<source uid>/``,
on Google Drive), transcribes, aligns and diarizes it, and writes the results next to
the job. This PC only reads: Drive for Desktop shows the files under G:, the app plays
the video from there and loads the lines and speakers (a few kilobytes per video).

Voice separation is not part of a batch; a video someone dubs is separated then (on the
same worker, reading the video where it is).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import db, project, series, settings

BATCH = 20          # videos per job: models load once per job; results are saved per video
STEPS = ["fetch", "asr", "align", "diarize"]


def _remote(pid: str) -> dict:
    return db.meta(pid).get("remote") or {}


def add(sid: str, entries: list[dict], clip: tuple[float | None, float | None] = (None, None)) -> dict:
    """Add feed entries to the series as remote sources: nothing is downloaded here."""
    added, skipped = [], []
    for e in entries:
        try:
            p = series.add_source(sid, (e.get("title") or e["id"])[:120], e.get("url") or e["id"], clip[0], clip[1],
                                  origin_id=e["id"], defer=True)
            added.append(p["id"])
        except ValueError as err:
            skipped.append({"id": e.get("id"), "reason": str(err)})
    return {"added": added, "skipped": skipped}


def queue(sid: str, root_id: str = "colab", batch: int = BATCH, height: int = 720, steps: list[str] | None = None,
          ids: list[str] | None = None) -> dict:
    """Queue the series' sources that have no lines yet and are not already queued (or
    just ``ids``) as bulk jobs on ``root_id``. Returns the job ids."""
    w = series.get(sid)
    r = settings.root(root_id)
    q = project.queue(r["id"])
    todo = []
    for p in db.rows("SELECT * FROM projects WHERE series_id=? ORDER BY position, created", sid):
        if ids is not None and p["id"] not in ids:
            continue
        rem = _remote(p["id"])
        if ids is None and (db.row("SELECT 1 FROM sentences WHERE project_id=?", p["id"]) or _state(p["id"]) in ("queued", "done")):
            continue
        if not (p["source"] or "").startswith("http"):
            continue  # a file on this PC cannot be fetched by a remote worker
        todo.append(p | {"dest": rem.get("dest") or f"library/{w['uid']}/{p['uid']}"})
    params = {"steps": steps or STEPS, "height": height, "asr_model": "large-v3", "language": w["src_lang"],
              "aligner": settings.aligner(w["src_lang"]), "max_speakers": w["settings"].get("max_speakers")}
    jobs = []
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        items = [{"id": p["uid"], "url": p["source"], "clip": [p["clip_start"], p["clip_end"]], "dest": p["dest"],
                  "title": p["name"]} for p in chunk]
        job = q.submit("bulk", params | {"items": items, "series": sid})
        db.run("INSERT OR REPLACE INTO jobs (id,project_id,stage,created,role,root) VALUES (?,?,?,?,?,?)",
               job, f"series:{sid}", "bulk", time.time(), "bulk", r["id"])
        for p in chunk:
            db.set_meta(p["id"], remote={"root": r["id"], "dest": p["dest"], "job": job, "item": p["uid"]})
        jobs.append(job)
    return {"jobs": jobs, "videos": len(todo), "root": r["id"]}


def _item_dir(pid: str) -> Path | None:
    rem = _remote(pid)
    if not rem.get("job"):
        return None
    return project.queue(rem["root"]).out_dir(rem["job"]) / rem["item"]


def _state(pid: str) -> str | None:
    """queued | done | failed for a remote source's latest batch item (None if never sent)."""
    d = _item_dir(pid)
    if d is None:
        return None
    try:
        if (d / "done.json").exists():
            return "done"
        if (d / "error.json").exists():
            return "failed"
    except OSError:
        return "queued"
    return "queued"


def status(sid: str) -> dict:
    """Batches and videos of the series: how far the remote worker is."""
    jobs = []
    for j in db.rows("SELECT * FROM jobs WHERE project_id=? AND stage='bulk' ORDER BY created", f"series:{sid}"):
        try:
            st = project.job_queue(j).status(j["id"])
        except OSError:
            st = {"state": "unreachable"}
        jobs.append({"id": j["id"], "state": st.get("state"), "progress": st.get("progress"), "note": st.get("note"),
                     "error": st.get("error"), "heartbeat": st.get("heartbeat"), "result": st.get("result")})
    videos = {"done": 0, "loaded": 0, "failed": 0, "queued": 0, "not_sent": 0}
    failures = []
    for p in db.rows("SELECT id, name FROM projects WHERE series_id=?", sid):
        if db.row("SELECT 1 FROM sentences WHERE project_id=?", p["id"]):
            videos["loaded"] += 1
            continue
        s = _state(p["id"])
        if s is None:
            videos["not_sent"] += 1
        else:
            videos[s] += 1
            if s == "failed":
                d = _item_dir(p["id"])
                try:
                    err = json.loads((d / "error.json").read_text(encoding="utf-8"))["error"]
                except (OSError, ValueError, KeyError):
                    err = ""
                failures.append({"id": p["id"], "name": p["name"], "error": err[-300:]})
    return {"jobs": jobs, "videos": videos, "failures": failures}


def load(sid: str, limit: int | None = None) -> dict:
    """Bring finished videos in: lines and speakers into the library; the video and its
    audio stay on Drive and are played from there."""
    loaded, errors = [], []
    for p in db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created", sid):
        if limit is not None and len(loaded) >= limit:
            break
        pid = p["id"]
        if _state(pid) != "done":
            continue
        has_lines = db.row("SELECT 1 FROM sentences WHERE project_id=?", pid)
        if has_lines and project.get(pid)["video"]:
            continue
        try:
            load_one(pid)
            loaded.append(pid)
        except (OSError, ValueError, KeyError) as e:
            errors.append({"id": pid, "error": f"{type(e).__name__}: {e}"})
    return {"loaded": loaded, "errors": errors}


def load_one(pid: str) -> dict:
    d = _item_dir(pid)
    rem = _remote(pid)
    done = json.loads((d / "done.json").read_text(encoding="utf-8"))
    video = Path(settings.root(rem["root"])["path"]) / rem["dest"] / "video.mp4"
    db.run("UPDATE projects SET video=?, audio=?, duration=? WHERE id=?", str(video), str(video), done.get("duration"), pid)
    fp = video.parent / "fingerprint.npy"
    if fp.exists():  # worked out on the worker: finding recurring parts needs no download
        import shutil

        shutil.copy2(fp, project.pdir(pid) / "fingerprint.npy")
    if not (d / "asr_spk.json").exists():
        return {"video": str(video)}  # a fetch-only batch: the media is here, the lines came another way
    asr = json.loads((d / "asr_spk.json").read_text(encoding="utf-8"))
    dia = json.loads((d / "diarization.json").read_text(encoding="utf-8"))
    return project.ingest_docs(pid, asr, dia)


def retry_failed(sid: str, root_id: str = "colab") -> dict:
    """Send the videos that failed back to the remote worker, in a new batch."""
    ids = [p["id"] for p in db.rows("SELECT id FROM projects WHERE series_id=?", sid) if _state(p["id"]) == "failed"]
    return queue(sid, root_id, ids=ids) if ids else {"jobs": [], "videos": 0, "root": root_id}


def fetch_remote(pid: str, root_id: str = "colab") -> str:
    """Bring one source's video into the Drive library (no analysis), e.g. a source that
    arrived in a work package without media."""
    p = project.get(pid)
    return queue(p["series_id"], root_id, steps=["fetch"], ids=[pid])["jobs"][0]
