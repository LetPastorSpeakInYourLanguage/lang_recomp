"""Follow jobs in a job folder until they all finish; prints state changes and the
newest log line of whatever is running.

    python scripts/watch.py local [job_id ...]      (folder id from Settings)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import project  # noqa: E402

root = sys.argv[1] if len(sys.argv) > 1 else "local"
q = project.queue(root)
ids = sys.argv[2:] or [d.name for d in sorted(q.layout.jobs.iterdir())
                       if (q.status(d.name).get("state") not in ("done", "failed"))]
t0, last, tail = time.time(), {}, {}
while ids and time.time() - t0 < 6 * 3600:
    for j in ids:
        st = q.status(j)
        key = (st.get("state"), round(st.get("progress") or 0, 2))
        if last.get(j) != key:
            last[j] = key
            print(f"+{time.time() - t0:5.0f}s {j[16:]:<22} {key[0]:<8} {key[1]:.2f} {(st.get('error') or '')[:200]}", flush=True)
        if st.get("state") == "running":
            lines = [ln for ln in q.log(j).splitlines() if ln.strip()]
            if lines and tail.get(j) != lines[-1]:
                tail[j] = lines[-1]
                print(f"         {lines[-1][:160]}", flush=True)
    if all(q.status(j).get("state") in ("done", "failed") for j in ids):
        break
    time.sleep(15)
print("finished:", {j[16:]: q.status(j).get("state") for j in ids})
