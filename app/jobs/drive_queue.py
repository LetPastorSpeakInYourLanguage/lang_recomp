"""Desktop side of the job-bundle protocol (see worker/lb_worker/protocol.py).

The desktop only ever writes job.json and in/; everything else in a job folder
belongs to the worker.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

_WORKER_PKG = Path(__file__).resolve().parents[2] / "worker"
if str(_WORKER_PKG) not in sys.path:
    sys.path.insert(0, str(_WORKER_PKG))

from lb_worker.protocol import (  # noqa: E402
    PROTOCOL_VERSION, QUEUED, STALE_AFTER_S, TERMINAL, Layout, new_job_id, now, read_json,
    write_json,
)

DEFAULT_ROOT = os.environ.get("LANGBRIDGE_ROOT", "G:/My Drive/LangBridge")


class DriveQueue:
    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.layout = Layout(root)
        self.layout.ensure()

    def submit(self, stage: str, params: dict | None = None,
               files: list[str | Path] = (), shared: list[str] = (),
               after: list[str] = ()) -> str:
        """Queue a job.

        files:  local files copied into the job's own in/ folder
        shared: root-relative paths already on Drive (project media, or another job's
                out/ files — see ``out_ref``), not copied
        after:  job ids that must be done first (their outputs are among ``shared``)
        """
        job_id = new_job_id(stage)
        jdir = self.layout.job_dir(job_id)
        (jdir / "in").mkdir(parents=True, exist_ok=True)
        inputs = list(shared)
        for f in files:
            f = Path(f)
            shutil.copy2(f, jdir / "in" / f.name)
            inputs.append(self.layout.rel(jdir / "in" / f.name))
        # job.json last: its appearance is what makes the job visible to the worker,
        # so the inputs are already in place when it is picked up.
        write_json(jdir / "job.json", {
            "protocol": PROTOCOL_VERSION, "job_id": job_id, "stage": stage,
            "params": params or {}, "inputs": inputs, "after": list(after), "created_at": now(),
        })
        return job_id

    def out_ref(self, job_id: str, name: str) -> str:
        """Root-relative path of a (future) output of another job."""
        return f"jobs/{job_id}/out/{name}"

    def put_media(self, project: str, path: str | Path) -> str:
        """Copy a file into the project's shared media folder; returns its root-relative path.
        A file already inside this job folder (e.g. a video a worker fetched into the
        library on Drive) is referenced where it is, never copied through this PC."""
        path = Path(path)
        try:
            return path.resolve().relative_to(self.layout.root.resolve()).as_posix()
        except ValueError:
            pass
        dst = self.layout.projects / project / "media" / path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_size != path.stat().st_size:
            shutil.copy2(path, dst)
        return self.layout.rel(dst)

    def status(self, job_id: str) -> dict:
        return read_json(self.layout.job_dir(job_id) / "status.json") or {"state": QUEUED}

    def out_dir(self, job_id: str) -> Path:
        return self.layout.job_dir(job_id) / "out"

    def log(self, job_id: str) -> str:
        p = self.layout.job_dir(job_id) / "log.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def wait(self, job_id: str, timeout_s: float = 900, poll_s: float = 3, on_change=None) -> dict:
        last = None
        deadline = now() + timeout_s
        while now() < deadline:
            st = self.status(job_id)
            if st.get("state") != last:
                last = st.get("state")
                if on_change:
                    on_change(st)
            if st.get("state") in TERMINAL:
                return st
            time.sleep(poll_s)
        raise TimeoutError(f"{job_id} still {last} after {timeout_s:.0f}s")

    def workers(self) -> list[dict]:
        """Known workers, each tagged online/offline by heartbeat age."""
        out = []
        for p in sorted(self.layout.workers.glob("*.json")):
            w = read_json(p)
            if not w:
                continue
            w["age_s"] = round(now() - w.get("heartbeat", 0), 1)
            w["online"] = w["age_s"] < STALE_AFTER_S
            out.append(w)
        return out
