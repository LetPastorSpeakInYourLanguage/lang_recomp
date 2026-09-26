"""The job-bundle protocol shared by the desktop app and the Colab worker.

A job is a folder under ``<root>/jobs/<job_id>/``. Every file in it has exactly one
writer, so Drive for Desktop and Colab's Drive mount never fight over a file:

    job.json     desktop, written once      what to run, with which inputs
    in/          desktop                    job-private inputs
    status.json  worker                     queued is implied by its absence
    out/         worker                     results
    log.txt      worker

Worker liveness lives in ``<root>/workers/<worker_id>.json`` (worker-only too).
Paths inside job.json are POSIX paths relative to the root, so the same bundle
resolves on Windows (G:\\My Drive\\LangBridge) and on Colab
(/content/drive/MyDrive/LangBridge).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

PROTOCOL_VERSION = 1

QUEUED, CLAIMED, RUNNING, DONE, FAILED = "queued", "claimed", "running", "done", "failed"
TERMINAL = {DONE, FAILED}

HEARTBEAT_S = 30
# A worker whose heartbeat is older than this is treated as gone. Generous, because
# Colab's Drive mount can take a minute or more to push a write back to Drive.
STALE_AFTER_S = 180


def now() -> float:
    return time.time()


def new_job_id(stage: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{stage}-{secrets.token_hex(2)}"


def write_json(path: Path, data: dict) -> None:
    """Write via a temp file and rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # On Windows the rename fails while another process (the app polling status)
    # has the target open; that lasts milliseconds, so retry briefly.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))


def read_json(path: Path) -> dict | None:
    """None when missing or mid-sync. Drive can briefly expose a truncated file, and
    Drive for Desktop on Windows can fail the read outright (EINVAL) while it swaps
    in a new version."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


class Layout:
    """Folder layout under the LangBridge root."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.jobs = self.root / "jobs"
        self.workers = self.root / "workers"
        self.projects = self.root / "projects"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs / job_id

    def resolve(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/"))

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def ensure(self) -> None:
        for d in (self.jobs, self.workers, self.projects):
            d.mkdir(parents=True, exist_ok=True)
