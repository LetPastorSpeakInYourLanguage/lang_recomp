"""Phase 0 check: queue a ping job and time the round trip through Drive and Colab.

    python scripts/ping.py [--timeout 900]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.jobs.drive_queue import DriveQueue  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()
    q = DriveQueue()
    ws = q.workers()
    print("workers:", [(w["worker_id"], "online" if w["online"] else f"offline {w['age_s']}s") for w in ws] or "none yet")
    t0 = time.time()
    job_id = q.submit("ping", {"echo": "hello from desktop", "sent_at": t0})
    print(f"queued {job_id}; waiting for a worker...")

    def show(st):
        print(f"  +{time.time() - t0:6.1f}s  {st.get('state')}")

    st = q.wait(job_id, timeout_s=a.timeout, on_change=show)
    rtt = time.time() - t0
    res = st.get("result", {})
    print(json.dumps(res, indent=2))
    if st["state"] == "done":
        seen = res.get("received_at", t0) - t0
        print(f"round trip {rtt:.1f}s  (desktop->worker saw it {seen:.1f}s, worker->desktop {rtt - seen:.1f}s)")
    else:
        print("FAILED:", st.get("error"))
        print(q.log(job_id))


if __name__ == "__main__":
    main()
