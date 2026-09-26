"""The worker loop: find queued jobs, claim, run grouped by model, write results back.

Run on Colab from lb_worker.ipynb. It can also run locally for a CPU smoke test:

    python -m lb_worker.loop --root "G:/My Drive/LangBridge" --once
"""
from __future__ import annotations

import argparse
import gc
import os
import secrets
import shutil
import socket
import threading
import time
import traceback
from pathlib import Path

from . import stages  # noqa: F401  (registers handlers)
from .protocol import (
    CLAIMED, DONE, FAILED, HEARTBEAT_S, PROTOCOL_VERSION, QUEUED, RUNNING, STALE_AFTER_S,
    TERMINAL, Layout, now, read_json, write_json,
)
from .registry import STAGES


class Ctx:
    """What a stage handler sees."""

    def __init__(self, worker: "Worker", job_id: str, job: dict):
        self.worker = worker
        self.job_id = job_id
        self.job = job
        self.params = job.get("params", {})
        self.layout = worker.layout
        self.work = worker.scratch / job_id
        self.inp = self.work / "in"
        self.out = self.work / "out"
        self.inp.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        self._log_lines: list[str] = []
        self._log_lock = threading.Lock()
        self.progress = 0.0
        self.drive_dir = worker.layout.job_dir(job_id)

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"  {self.job_id}: {msg}", flush=True)
        with self._log_lock:
            self._log_lines.append(line)

    def flush_log(self) -> None:
        """Rewrite log.txt on Drive with everything so far. Called with every
        heartbeat, so a runtime that dies still leaves its trail behind."""
        with self._log_lock:
            text = "\n".join(self._log_lines) + "\n"
        tmp = self.drive_dir / ".log.txt.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.drive_dir / "log.txt")

    def checkpoint(self) -> None:
        """Push out/ to Drive now. Long stages call this after each unit of work,
        so a crash only loses the unit in progress."""
        shutil.copytree(self.out, self.drive_dir / "out", dirs_exist_ok=True)
        self.flush_log()

    def cancelled(self) -> bool:
        return (self.drive_dir / "cancel").exists()

    def set_progress(self, frac: float, note: str | None = None) -> None:
        self.progress = max(0.0, min(1.0, frac))
        if note:
            self.log(note)

    def input(self, rel: str) -> Path:
        """Local copy of an input named by its root-relative path in job.json."""
        return self.inp / Path(rel).name

    def model(self, key: str, loader):
        """Loaded weights shared across jobs with the same key within this session."""
        return self.worker.model(key, loader)


class Worker:
    def __init__(self, root: str | Path, scratch: str | Path = "/content/work", poll_s: float = 10,
                 stages: list[str] | None = None):
        self.layout = Layout(root)
        # Which stages this worker takes. A CPU worker on the PC leaves voicing alone.
        self.stages = set(stages or STAGES) & set(STAGES)
        self.layout.ensure()
        self.scratch = Path(scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.poll_s = poll_s
        self.worker_id = f"{socket.gethostname()}-{secrets.token_hex(2)}"
        self.started = now()
        self.current: str | None = None
        self._models: dict[str, object] = {}
        self._model_key: str | None = None

    # ---- liveness -------------------------------------------------------------------
    def beat(self, **extra) -> None:
        try:
            self._beat(**extra)
        except OSError as e:  # a missed heartbeat must never take the worker down
            print(f"heartbeat skipped: {e}", flush=True)

    def _beat(self, **extra) -> None:
        write_json(self.layout.workers / f"{self.worker_id}.json", {
            "worker_id": self.worker_id, "protocol": PROTOCOL_VERSION, "started": self.started,
            "heartbeat": now(), "current_job": self.current, "stages": sorted(self.stages),
            "device": _device(), **extra,
        })

    # ---- models ---------------------------------------------------------------------
    def model(self, key: str, loader):
        if key not in self._models:
            self._models[key] = loader()
        return self._models[key]

    def switch_models(self, key: str) -> None:
        """Free whatever the previous stage group loaded; a T4 cannot hold several."""
        if self._model_key not in (None, key) and self._models:
            self._models.clear()
            gc.collect()
            try:
                import torch

                torch.cuda.empty_cache()
            except ImportError:
                pass
        self._model_key = key

    # ---- queue ----------------------------------------------------------------------
    def pending(self) -> list[tuple[str, dict]]:
        found = []
        if not self.layout.jobs.exists():
            return found
        for d in sorted(self.layout.jobs.iterdir()):
            if not d.is_dir():
                continue
            job = read_json(d / "job.json")
            if not job or job.get("stage") not in self.stages:
                continue
            st = read_json(d / "status.json")
            if (d / "cancel").exists():
                if not st or st.get("state") not in TERMINAL:
                    self._status(d.name, FAILED, error="cancelled")
                continue
            if not self._deps_ready(d.name, job):
                continue
            if st is None or st.get("state") == QUEUED:
                found.append((d.name, job))
            elif st.get("state") in (CLAIMED, RUNNING) and st.get("worker_id") != self.worker_id \
                    and now() - st.get("heartbeat", 0) > STALE_AFTER_S:
                found.append((d.name, job))  # orphaned by a dead session: take it over
        # Group by model so each set of weights loads once.
        found.sort(key=lambda it: (STAGES[it[1]["stage"]].model_key, it[0]))
        return found

    def _deps_ready(self, job_id: str, job: dict) -> bool:
        """``after`` lists jobs whose outputs this one reads. Their status files were
        written by a worker, usually this one, so no sync lag is involved."""
        for dep in job.get("after", []):
            st = read_json(self.layout.job_dir(dep) / "status.json") or {}
            if st.get("state") == FAILED:
                mine = read_json(self.layout.job_dir(job_id) / "status.json") or {}
                if mine.get("state") != FAILED:
                    self._status(job_id, FAILED, error=f"dependency {dep} failed")
                return False
            if st.get("state") != DONE:
                return False
        return True

    def _status(self, job_id: str, state: str, **extra) -> dict:
        st = {"state": state, "worker_id": self.worker_id, "heartbeat": now(), **extra}
        write_json(self.layout.job_dir(job_id) / "status.json", st)
        return st

    def run_job(self, job_id: str, job: dict) -> None:
        stage = STAGES[job["stage"]]
        jdir = self.layout.job_dir(job_id)
        self.current = job_id
        claimed_at = now()
        self._status(job_id, CLAIMED, claimed_at=claimed_at)
        ctx = Ctx(self, job_id, job)
        # Taking over from a session that died: keep its log, and start from the
        # outputs it had already checkpointed so finished work is not redone.
        prev = jdir / "log.txt"
        if prev.exists():
            ctx._log_lines = prev.read_text(encoding="utf-8").splitlines() + ["---- resumed ----"]
        if (jdir / "out").exists():
            shutil.copytree(jdir / "out", ctx.out, dirs_exist_ok=True)
        ctx.log(f"claimed by {self.worker_id}; stage={stage.name}")
        ctx.flush_log()

        stop = threading.Event()

        def heartbeat():
            while not stop.wait(HEARTBEAT_S):
                self._status(job_id, RUNNING, claimed_at=claimed_at, progress=ctx.progress)
                self.beat()
                try:
                    ctx.flush_log()
                except OSError:
                    pass

        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()
        t0 = now()
        try:
            for rel in job.get("inputs", []):
                src = self.layout.resolve(rel)
                shutil.copy2(src, ctx.inp / src.name)
            ctx.log(f"inputs copied ({len(job.get('inputs', []))}) in {now() - t0:.1f}s")
            self._status(job_id, RUNNING, claimed_at=claimed_at, progress=0.0)
            self.switch_models(stage.model_key)
            result = stage.fn(ctx) or {}
            stop.set()
            ctx.log(f"done in {now() - t0:.1f}s")
            ctx.checkpoint()
            self._status(job_id, DONE, claimed_at=claimed_at, finished_at=now(),
                         elapsed_s=round(now() - t0, 2), result=result)
        except Exception as e:  # a failing stage must not kill the worker
            stop.set()
            ctx.log("FAILED\n" + traceback.format_exc())
            try:
                ctx.checkpoint()
            except OSError:
                pass
            self._status(job_id, FAILED, claimed_at=claimed_at, finished_at=now(),
                         error=f"{type(e).__name__}: {e}")
        finally:
            self.current = None

    def code_version(self) -> str:
        """Stamp written by scripts/sync_worker.py each time new code is published."""
        try:
            return (self.layout.root / "worker" / "VERSION").read_text().strip()
        except OSError:
            return ""

    def serve(self, once: bool = False, idle_exit_min: float | None = None) -> str:
        """Returns "reload" when newer worker code was published (the notebook then
        re-copies the package and starts again), otherwise "idle"/"once"."""
        print(f"worker {self.worker_id} watching {self.layout.jobs}  stages={sorted(self.stages)}", flush=True)
        started_on = self.code_version()
        last_work = now()
        while True:
            if not once and self.code_version() != started_on:
                print("new worker code published on Drive; reloading", flush=True)
                return "reload"
            self.beat()
            # One job at a time, re-scanning after each: a finished job can unblock
            # its dependants, which should run in this same pass.
            while jobs := self.pending():
                job_id, job = jobs[0]
                self.run_job(job_id, job)
                last_work = now()
                if self.code_version() != started_on:
                    break  # pick up new code before the next job
            if once:
                return "once"
            if idle_exit_min is not None and now() - last_work > idle_exit_min * 60:
                print("queue empty; exiting", flush=True)
                return "idle"
            if self.code_version() == started_on:
                time.sleep(self.poll_s)


def _device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return torch.xpu.get_device_name(0)
        return "cpu"
    except ImportError:
        return "cpu"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--scratch", default="/content/work")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=float, default=10)
    ap.add_argument("--stages", default="", help="comma list; default: every registered stage")
    a = ap.parse_args()
    stages = [s for s in a.stages.split(",") if s] or None
    Worker(a.root, a.scratch, a.poll, stages).serve(once=a.once)


if __name__ == "__main__":
    main()
