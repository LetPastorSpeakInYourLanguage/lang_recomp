"""Local background tasks (downloads, ffmpeg, translation) — the desktop's half of
the job list; Colab jobs live in the Drive queue."""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid

_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_serial: dict[str, queue.Queue] = {}  # one FIFO and one worker thread per serial group


def start(project_id: str, kind: str, fn, *args, serial: str | None = None) -> str:
    """Run ``fn(*args, update)`` in the background. Tasks sharing a ``serial`` name run
    one at a time, in the order started (e.g. downloads on a slow connection); the
    waiting ones show as queued."""
    tid = uuid.uuid4().hex[:8]
    t = {"id": tid, "project_id": project_id, "kind": kind, "state": "queued" if serial else "running",
         "note": "", "progress": 0.0, "started": time.time(), "finished": None, "error": None}
    with _lock:
        _tasks[tid] = t

    def update(progress: float | None = None, note: str | None = None):
        if progress is not None:
            t["progress"] = progress
        if note is not None:
            t["note"] = note

    def body():
        t["state"] = "running"
        try:
            fn(*args, update)
            t["state"] = "done"
            t["progress"] = 1.0
        except Exception as e:
            t["state"] = "failed"
            t["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        t["finished"] = time.time()

    if serial is None:
        threading.Thread(target=body, daemon=True).start()
    else:
        with _lock:
            q = _serial.get(serial)
            if q is None:
                q = _serial[serial] = queue.Queue()
                threading.Thread(target=_drain, args=(q,), daemon=True).start()
        q.put(body)
    return tid


def _drain(q: queue.Queue) -> None:
    while True:
        q.get()()


def list_for(project_id: str | None = None) -> list[dict]:
    with _lock:
        ts = list(_tasks.values())
    return sorted([t for t in ts if project_id in (None, t["project_id"])], key=lambda t: -t["started"])


def busy(project_id: str, kind: str) -> bool:
    return any(t["kind"] == kind and t["state"] in ("running", "queued") for t in list_for(project_id))
