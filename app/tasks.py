"""Local background tasks (downloads, ffmpeg, translation) — the desktop's half of
the job list; Colab jobs live in the Drive queue."""
from __future__ import annotations

import threading
import time
import traceback
import uuid

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def start(project_id: str, kind: str, fn, *args) -> str:
    tid = uuid.uuid4().hex[:8]
    t = {"id": tid, "project_id": project_id, "kind": kind, "state": "running",
         "note": "", "progress": 0.0, "started": time.time(), "finished": None, "error": None}
    with _lock:
        _tasks[tid] = t

    def update(progress: float | None = None, note: str | None = None):
        if progress is not None:
            t["progress"] = progress
        if note is not None:
            t["note"] = note

    def body():
        try:
            fn(*args, update)
            t["state"] = "done"
            t["progress"] = 1.0
        except Exception as e:
            t["state"] = "failed"
            t["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        t["finished"] = time.time()

    threading.Thread(target=body, daemon=True).start()
    return tid


def list_for(project_id: str | None = None) -> list[dict]:
    with _lock:
        ts = list(_tasks.values())
    return sorted([t for t in ts if project_id in (None, t["project_id"])], key=lambda t: -t["started"])


def busy(project_id: str, kind: str) -> bool:
    return any(t["kind"] == kind and t["state"] == "running" for t in list_for(project_id))
