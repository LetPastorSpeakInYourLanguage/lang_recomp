"""One separation worker: its own separator, a list of files. The parallel bench starts
several of these on one GPU, so one computes while the others do their CPU steps.

    python sep_worker.py --dest DIR --batch 8 FILE [FILE ...]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # …/worker
from lb_worker.stages.analysis import load_separator, separate_file  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dest", required=True)
ap.add_argument("--batch", type=int, default=1)
ap.add_argument("--autocast", action="store_true")
ap.add_argument("files", nargs="+")
a = ap.parse_args()

sep = load_separator(None, 2, lambda *_: None, batch_size=a.batch, autocast=a.autocast)
print("ready", flush=True)  # the parent starts timing when every worker is loaded
sys.stdin.readline()
t = time.time()
for k, f in enumerate(a.files):
    separate_file(sep, Path(f), Path(a.dest) / "tmp" / str(k), Path(a.dest) / str(k), lambda *_: None)
print(f"done {time.time() - t:.1f}", flush=True)
