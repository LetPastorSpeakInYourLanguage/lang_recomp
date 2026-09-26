"""Runs: send the pipeline — end to end, or up to a stage for a person to check — to a
device (Colab through Drive, or this PC's worker), for a series, chosen videos, or every
video in a folder on that device.

A run is one ``pipeline`` job (worker/lb_worker/stages/run.py). The app writes into the
device's folder ``runs/<run id>/``: ``work.lbwork`` (the work as it is here, people's
checks included, media by reference) and ``manifest.json`` (what to do). The device
publishes ``result.lbwork`` and ``state.json`` as it goes; opening the results imports
them by uid (manual truth) with media left where they are — on Drive they play from G:.

Checking between stages is just another run: stop after, say, transcribe; check the
transcript here; then run from translate — the next run starts from the work as it is
here, with the corrections.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import db, libraries, package, project, series, settings

STAGES = ["fetch", "transcribe", "translate", "voice", "mix"]
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus"}
SUBS = (".srt", ".vtt")
DEFAULTS = {"dub_limit": None, "captions_download": 0, "captions_align": 0, "align_subtitles": True,
            "height": 720, "takes": 1, "asr_model": "large-v3", "assume_checked": True, "mix_threads": 2}


def _root(root_id: str) -> Path:
    return Path(settings.root(root_id)["path"])


def folder_sources(sid: str, folder: str, root_id: str) -> list[str]:
    """Every video in a folder on the device becomes a source of the work (once), with
    the subtitles beside it (same name, .srt/.vtt) as its transcript. The folder must
    be where the device can read it: under the device's folder tree (for Colab: in the
    same Google Drive)."""
    root, f = _root(root_id), Path(folder)
    if not f.is_dir():
        raise ValueError(f"not a folder: {folder}")
    base = root.parent if settings.root(root_id)["kind"] == "colab" else Path(f.anchor)
    try:
        f.resolve().relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"the folder must be on the device that runs it (inside {base})")
    rel = lambda p: Path(*([".."] * len(root.resolve().relative_to(base.resolve()).parts)),  # noqa: E731
                         p.resolve().relative_to(base.resolve())).as_posix()
    have = {r["source"] for r in db.rows("SELECT source FROM projects WHERE series_id=?", sid)}
    added = []
    for v in sorted(p for p in f.iterdir() if p.suffix.lower() in VIDEO):
        src = f"root:{rel(v)}"
        if src in have:
            continue
        p = series.add_source(sid, v.stem[:120], src, defer=True)
        db.run("UPDATE projects SET video=?, audio=? WHERE id=?", str(v), str(v), p["id"])
        sub = next((v.with_suffix(s) for s in SUBS if v.with_suffix(s).exists()), None)
        if sub:
            db.set_meta(p["id"], subtitles=str(sub), refs={"subtitles": libraries.device_ref(root_id, sub)})
        added.append(p["id"])
    return added


def create(sid: str, root_id: str, stages: list[str] | None = None, sources: list[str] | None = None,
           folder: str | None = None, options: dict | None = None) -> dict:
    """Send a run for one work to a device. ``stages``: which (in pipeline order);
    ``sources``: project ids (default: every source of the work); ``folder``: add a
    folder's videos to the work first."""
    if folder:
        added = folder_sources(sid, folder, root_id)
        sources = (sources or []) + added if sources is not None else None
    pids = [p["id"] for p in db.rows("SELECT id FROM projects WHERE series_id=? ORDER BY position, created", sid)]
    if sources is not None:
        pids = [p for p in pids if p in set(sources)]
    return create_for(pids, root_id, stages, options, name=series.get(sid)["name"], owner=f"series:{sid}")


def create_for(pids: list[str], root_id: str, stages: list[str] | None = None, options: dict | None = None,
               name: str = "run", owner: str | None = None) -> dict:
    """Send a run for any videos — of one work or of many (a library selection) — to a
    device. Videos of different works are batched together; each work gets its results."""
    r = settings.root(root_id)
    stages = [s for s in STAGES if s in (stages or STAGES)]
    order = {pid: i for i, pid in enumerate(pids)}
    sids = sorted({project.get(p)["series_id"] for p in pids}, key=lambda s: min(order[p] for p in pids if project.get(p)["series_id"] == s))
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', name.lower())[:24].strip('-')}"
    d = _root(root_id) / "runs" / run_id
    (d / "works").mkdir(parents=True, exist_ok=True)
    opts = DEFAULTS | (options or {})
    opts["aligners"] = settings.load()["aligners"]
    opts["keep_words"] = settings.load().get("keep_words") or []
    works = []
    for sid in sids:
        w = series.get(sid)
        package.export(sid, w["targets"], media="ref", out=d / "works" / f"{w['uid']}.lbwork", ref_root=_root(root_id),
                       note=f"run {run_id}")
        works.append({"uid": w["uid"], "file": f"works/{w['uid']}.lbwork", "src_lang": w["src_lang"], "targets": w["targets"]})
    (d / "manifest.json").write_text(json.dumps({
        "run": run_id, "name": name, "created": time.time(), "works": works, "src_lang": works[0]["src_lang"] if works else "en",
        "stages": stages, "sources": [project.get(p)["uid"] for p in pids], "options": opts},
        ensure_ascii=False, indent=1), encoding="utf-8")
    q = project.queue(r["id"])
    job = q.submit("pipeline", {"run": run_id})
    for owner_id in ([owner] if owner else [f"series:{s}" for s in sids]):
        db.run("INSERT OR REPLACE INTO jobs (id,project_id,stage,created,role,root) VALUES (?,?,?,?,?,?)",
               f"{job}" if owner_id == (owner or f"series:{sids[0]}") else f"{job}@{owner_id}", owner_id, "pipeline",
               time.time(), run_id, r["id"])
    return {"run": run_id, "job": job, "root": r["id"], "videos": len(pids), "works": len(sids), "stages": stages}


def listing(owner: str) -> list[dict]:
    """Runs of a work ("series:<id>") or a library ("library:<id>"), newest first."""
    return [status(j["root"], j["role"], j["id"].split("@")[0]) for j in db.rows(
        "SELECT * FROM jobs WHERE project_id=? AND stage='pipeline' ORDER BY created DESC", owner)]


def status(root_id: str, run_id: str, job_id: str | None = None) -> dict:
    """Where a run is: stages done per video, results saved, the captions report."""
    d = _root(root_id) / "runs" / run_id
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        state = json.loads((d / "state.json").read_text(encoding="utf-8")) if (d / "state.json").exists() else {}
        st = project.queue(root_id).status(job_id) if job_id else {}
        report = json.loads((d / "report.json").read_text(encoding="utf-8")) if (d / "report.json").exists() else None
    except (OSError, ValueError):
        return {"run": run_id, "root": root_id, "state": "unreachable"}
    srcs = state.get("sources", {})
    return {"run": run_id, "name": man.get("name"), "job": job_id, "root": root_id, "state": st.get("state"),
            "progress": st.get("progress"), "note": st.get("note"), "stages": man["stages"], "videos": len(man["sources"]),
            "works": len(man.get("works") or [1]),
            "done": {s: sum(1 for v in srcs.values() if v.get(s) == "done") for s in STAGES},
            "failed": sum(1 for v in srcs.values() if any(str(x).startswith("failed") for x in v.values())),
            "saved": sorted(state.get("stages", {})), "has_results": bool(list((d / "results").glob("*.lbwork")))
            if (d / "results").exists() else False, "created": man["created"], "finished": state.get("finished"),
            "timings": state.get("timings", {}), "report": report}


def open_results(root_id: str, run_id: str) -> dict:
    """Bring a run's results in: by uid, people's work here kept, media left on the device."""
    d = _root(root_id) / "runs" / run_id / "results"
    files = sorted(d.glob("*.lbwork")) if d.exists() else []
    if not files:
        raise ValueError("this run has not saved results yet")
    reps = [package.import_work(f, fetch=False, ref_root=_root(root_id)) for f in files]
    return {"works": [r["work"] for r in reps], "sources": {k: [x for r in reps for x in r["sources"][k]] for k in ("added", "matched")},
            "lines": sum(r["lines"] for r in reps), "notes": [n for r in reps for n in r["notes"]]}
