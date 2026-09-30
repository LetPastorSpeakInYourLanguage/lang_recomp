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

from . import db, libraries, package, project, series, settings, tasks

STAGES = ["fetch", "transcribe", "translate", "voice", "mix"]
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus"}
SUBS = (".srt", ".vtt")
DEFAULTS = {"dub_limit": None, "captions_download": 0, "captions_align": 0, "align_subtitles": True,
            "height": 720, "takes": 1, "asr_model": "large-v3", "assume_checked": True, "mix_threads": 2}


def _root(root_id: str) -> Path:
    """Where a device's runs and library are: a team workspace keeps them in ``.lb/``
    (notebooks/lang_bridge.ipynb, lb_core/workspace); older output folders at the top."""
    p = Path(settings.root(root_id)["path"])
    return p / ".lb" if (p / ".lb").is_dir() else p


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
               name: str = "run", owner: str | None = None, submit: bool = True) -> dict:
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
    if r["kind"] in settings.NOTEBOOK_KINDS:
        submit = False  # never watched: a person runs it with notebooks/lang_bridge.ipynb
    # prepared only (no job): someone runs the folder with the research runner (run_manifest)
    job = project.queue(r["id"]).submit("pipeline", {"run": run_id}) if submit else f"{PREPARED}{run_id}"
    for owner_id in ([owner] if owner else [f"series:{s}" for s in sids]):
        db.run("INSERT OR REPLACE INTO jobs (id,project_id,stage,created,role,root) VALUES (?,?,?,?,?,?)",
               f"{job}" if owner_id == (owner or f"series:{sids[0]}") else f"{job}@{owner_id}", owner_id, "pipeline",
               time.time(), run_id, r["id"])
    return {"run": run_id, "job": None if job.startswith(PREPARED) else job, "dir": None if submit else str(d),
            "root": r["id"], "videos": len(pids), "works": len(sids), "stages": stages}


PREPARED = "prepared-"  # jobs-row id of a run that is only prepared (no queue job)


SETTLE_S = 60  # a results file untouched this long is complete on this PC (Drive has synced it)


def listing(owner: str, auto_open: bool = True) -> list[dict]:
    """Runs of a work ("series:<id>") or a library ("library:<id>"), newest first. Results
    a run saved since they were last opened are brought in by themselves (in the background)."""
    out = [status(j["root"], j["role"], j["id"].split("@")[0]) for j in db.rows(
        "SELECT * FROM jobs WHERE project_id=? AND stage='pipeline' ORDER BY created DESC", owner)]
    return _open_new(owner, out) if auto_open else out


def scan(root_id: str, auto_open: bool = True) -> list[dict]:
    """Every run in a device's folder, whoever made it (the app, or a notebook on its own),
    newest first; new results come into the app by themselves, as in ``listing``."""
    d = _root(root_id) / "runs"
    found = sorted((p for p in d.glob("*/manifest.json")), key=lambda p: p.parent.name, reverse=True) if d.exists() else []
    out = [status(root_id, p.parent.name, f"{PREPARED}{p.parent.name}") for p in found]
    return _open_new(f"root:{root_id}", out) if auto_open else out


def _open_new(owner: str, out: list[dict]) -> list[dict]:
    for r in out:
        at = r.get("results_at")
        fresh = at and at > (r.get("opened_at") or 0) and time.time() - at > SETTLE_S
        if fresh and (r["root"], r["run"]) not in _opening:
            _opening.add((r["root"], r["run"]))
            r["opening"] = True
            tasks.start(owner, "open run results", _auto_open, r["root"], r["run"], serial="run-results")
    return out


_opening: set = set()


def _auto_open(root_id: str, run_id: str, update) -> None:
    try:
        update(None, run_id)
        open_results(root_id, run_id)
    finally:
        _opening.discard((root_id, run_id))


def _opened_path() -> Path:
    return db.DATA / "run_results_opened.json"


def _opened() -> dict:
    try:
        return json.loads(_opened_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status(root_id: str, run_id: str, job_id: str | None = None) -> dict:
    """Where a run is: stages done per video, results saved, the captions report."""
    d = _root(root_id) / "runs" / run_id
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        state = json.loads((d / "state.json").read_text(encoding="utf-8")) if (d / "state.json").exists() else {}
        st = project.queue(root_id).status(job_id) if job_id and not job_id.startswith(PREPARED) else {}
        report = json.loads((d / "report.json").read_text(encoding="utf-8")) if (d / "report.json").exists() else None
    except (OSError, ValueError):
        return {"run": run_id, "root": root_id, "state": "unreachable"}
    srcs = state.get("sources", {})
    res = sorted((d / "results").glob("*.lbwork")) if (d / "results").exists() else []
    results_at = max((f.stat().st_mtime for f in res), default=None)
    if settings.root(root_id).get("kind") in settings.NOTEBOOK_KINDS:  # run by hand in a notebook: no queue to ask
        job_id = f"{PREPARED}{run_id}"
    if job_id and job_id.startswith(PREPARED):  # run by hand: only the folder tells how far it got
        seen = max((p.stat().st_mtime for p in (d / "state.json", d / "log.txt") if p.exists()), default=0)
        st = {"state": "failed" if state.get("error") else "done" if state.get("finished") else "prepared" if not srcs
              else "running" if time.time() - seen < 15 * 60 else "paused"}
        log = d / "log.txt"
        if log.exists():  # the last line the notebook printed
            try:
                with open(log, "rb") as f:
                    f.seek(max(0, log.stat().st_size - 400))
                    st["note"] = f.read().decode("utf-8", "replace").strip().splitlines()[-1][9:]
            except (OSError, IndexError):
                pass
        if state.get("error"):
            st["note"] = state["error"]
        job_id = None
    return {"run": run_id, "name": man.get("name"), "job": job_id, "root": root_id, "state": st.get("state"),
            "progress": st.get("progress"), "note": st.get("note"), "stages": man["stages"], "videos": len(man["sources"]),
            "works": len(man.get("works") or [1]),
            "done": {s: sum(1 for v in srcs.values() if v.get(s) == "done") for s in STAGES},
            "failed": sum(1 for v in srcs.values() if any(str(x).startswith("failed") for x in v.values())),
            "saved": sorted(state.get("stages", {})), "has_results": bool(res), "results_at": results_at,
            "opened_at": _opened().get(f"{root_id}/{run_id}"), "created": man["created"], "finished": state.get("finished"),
            "timings": state.get("timings", {}), "report": report}


def open_results(root_id: str, run_id: str) -> dict:
    """Bring a run's results in: by uid, people's work here kept, media left on the device."""
    d = _root(root_id) / "runs" / run_id / "results"
    files = sorted(d.glob("*.lbwork")) if d.exists() else []
    if not files:
        raise ValueError("this run has not saved results yet")
    at = max(f.stat().st_mtime for f in files)
    reps = [package.import_work(f, fetch=False, ref_root=_root(root_id)) for f in files]
    seen = _opened()
    seen[f"{root_id}/{run_id}"] = at
    _opened_path().write_text(json.dumps(seen), encoding="utf-8")
    return {"works": [r["work"] for r in reps], "sources": {k: [x for r in reps for x in r["sources"][k]] for k in ("added", "matched")},
            "lines": sum(r["lines"] for r in reps), "notes": [n for r in reps for n in r["notes"]]}
