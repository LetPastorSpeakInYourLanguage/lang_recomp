"""Publish the worker to Drive: copies worker/lb_worker and (re)writes lb_worker.ipynb.

    python scripts/sync_worker.py [--root "G:/My Drive/LangBridge"]

The notebook itself stays thin and rarely changes; it copies lb_worker/ from Drive
at start-up, so editing the package locally and re-running this script is enough
to ship new stages to the next Colab session.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SRC = HERE / "worker" / "lb_worker"


def cell(kind: str, src: str) -> dict:
    c = {"cell_type": kind, "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


NOTEBOOK_CELLS = [
    cell("markdown", """
# Lang-Bridge worker

**Runtime → Change runtime type → T4 GPU**, then **Runtime → Run all** whenever the
app shows jobs queued for the Colab folder.

It runs every queued job in `MyDrive/LangBridge/jobs/`, then **stops and releases the
GPU** by itself. It never sits polling, which is what Colab's terms ask for:
open it when there is work, let it finish, done.
Optional: add an `HF_TOKEN` secret (key icon in the left bar) for gated models.
"""),
    cell("code", """
# Set to False to keep the runtime (and its GPU) after the queue is done.
RELEASE_GPU_WHEN_DONE = True

from google.colab import drive
drive.mount('/content/drive')
ROOT = '/content/drive/MyDrive/LangBridge'

# Everything re-downloadable lives on Drive, so only the first session pays for it:
# Hugging Face models, torch hub weights, pip's wheel cache, and big checkpoints.
import os
CACHE = f'{ROOT}/cache'
for k, sub in {'HF_HOME': 'hf', 'TORCH_HOME': 'torch', 'PIP_CACHE_DIR': 'pip', 'LB_CACHE': ''}.items():
    os.environ[k] = f'{CACHE}/{sub}'.rstrip('/')
    os.makedirs(os.environ[k], exist_ok=True)
print('model cache:', CACHE)
"""),
    cell("code", """
import os, sys, shutil
try:
    from google.colab import userdata
    os.environ['HF_TOKEN'] = userdata.get('HF_TOKEN')
    print('HF_TOKEN loaded from Colab secrets')
except Exception as e:
    print('no HF_TOKEN secret (only needed for gated models):', type(e).__name__)
"""),
    cell("code", """
# Work through the queue, then stop. A short grace period catches jobs the app is
# still syncing to Drive. If new worker code is published mid-run, it reloads first.
sys.path.insert(0, '/content/lb')
while True:
    shutil.rmtree('/content/lb', ignore_errors=True)
    shutil.copytree(f'{ROOT}/worker/lb_worker', '/content/lb/lb_worker',
                    ignore=shutil.ignore_patterns('__pycache__'))
    for m in [m for m in sys.modules if m.startswith('lb_worker')]:
        del sys.modules[m]
    from lb_worker.loop import Worker
    if Worker(ROOT, scratch='/content/work', poll_s=10).serve(idle_exit_min=1) != 'reload':
        break
print('All queued jobs are done.')
if RELEASE_GPU_WHEN_DONE:
    from google.colab import runtime
    print('Releasing the GPU runtime.')
    runtime.unassign()
"""),
]


def notebook() -> dict:
    return {
        "nbformat": 4, "nbformat_minor": 0, "cells": NOTEBOOK_CELLS,
        "metadata": {
            "accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="G:/My Drive/LangBridge")
    root = Path(ap.parse_args().root)
    dst = root / "worker" / "lb_worker"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    nb = root / "worker" / "lb_worker.ipynb"
    nb.write_text(json.dumps(notebook(), indent=1), encoding="utf-8")
    # Written last: a running worker reloads when this changes, so the package it
    # re-copies is already complete.
    (root / "worker" / "VERSION").write_text(time.strftime("%Y%m%d-%H%M%S"))
    files = sorted(p.relative_to(root).as_posix() for p in (root / "worker").rglob("*") if p.is_file())
    print(f"synced {len(files)} files to {root / 'worker'}")
    for f in files:
        print("  ", f)


if __name__ == "__main__":
    main()
