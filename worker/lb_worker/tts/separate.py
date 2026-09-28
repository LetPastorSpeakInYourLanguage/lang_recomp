"""Separation in its own process (on a second GPU: CUDA_VISIBLE_DEVICES=1), fed one video
per line on stdin as they are downloaded, while transcription uses the first GPU.

    stdin lines: {"name": "…", "src": "video.mp4", "tmp": "work dir", "dest": "media dir"}
    stdout:      "separated <name> in N s" / "separation failed for <name>: …"
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # …/worker
from lb_worker.stages.analysis import load_separator, separate_file  # noqa: E402

sep = load_separator(None, 2, lambda m: print(m, flush=True))
print("separator ready", flush=True)
for line in sys.stdin:
    if not line.strip():
        continue
    job = json.loads(line)
    t = time.time()
    try:
        separate_file(sep, Path(job["src"]), Path(job["tmp"]), Path(job["dest"]), lambda *_: None)
        print(f"separated {job['name']} in {time.time() - t:.0f} s", flush=True)
    except Exception as e:  # the parent separates it again on its own GPU
        print(f"separation failed for {job['name']}: {type(e).__name__}: {str(e)[:300]}", flush=True)
