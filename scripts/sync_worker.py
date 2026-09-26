"""Publish the worker to Drive: copies worker/lb_worker and app/, and (re)writes lb_worker.ipynb.

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
# Lang-Bridge on Colab

This notebook does the work the Lang-Bridge app sends to your Google Drive: whole **runs**
(fetch → transcribe → translate → voice → mix, for a series, chosen videos or a library
folder) and single jobs.

1. **Runtime → Change runtime type → T4 GPU**
2. **Runtime → Run all**

It works through everything the app sent, saving results to Drive as it goes — it is safe
to stop at any time; running it again carries on where it stopped. When everything is
done it releases the GPU. Then open the results in the app.

Speaker detection uses a gated model: add your Hugging Face token once as a Colab secret
named `HF_TOKEN` (key icon in the left bar).
"""),
    cell("code", """
# 1 · Connect Google Drive and keep downloaded models on it (only the first session pays for them)
RELEASE_GPU_WHEN_DONE = True   # False keeps the GPU after the work is done

from google.colab import drive
drive.mount('/content/drive')
ROOT = '/content/drive/MyDrive/LangBridge'

import os
CACHE = f'{ROOT}/cache'
for k, sub in {'HF_HOME': 'hf', 'TORCH_HOME': 'torch', 'PIP_CACHE_DIR': 'pip', 'LB_CACHE': ''}.items():
    os.environ[k] = f'{CACHE}/{sub}'.rstrip('/')
    os.makedirs(os.environ[k], exist_ok=True)
print('Drive connected; models are kept in', CACHE)
"""),
    cell("code", """
# 2 · The Hugging Face token (for speaker detection)
try:
    from google.colab import userdata
    os.environ['HF_TOKEN'] = userdata.get('HF_TOKEN')
    print('Hugging Face token found')
except Exception as e:
    print('No HF_TOKEN secret: speaker detection will not run until you add it.', type(e).__name__)
"""),
    cell("code", """
# 3 · Do the work the app sent (runs and jobs), then stop
import sys, shutil, time
sys.path.insert(0, '/content/lb')
started = time.time()
while True:
    # the Lang-Bridge code published to Drive by the app: the worker and the app's own logic
    shutil.rmtree('/content/lb', ignore_errors=True)
    for pkg in ('lb_worker', 'app'):
        shutil.copytree(f'{ROOT}/worker/{pkg}', f'/content/lb/{pkg}', ignore=shutil.ignore_patterns('__pycache__'))
    for m in [m for m in sys.modules if m.split('.')[0] in ('lb_worker', 'app')]:
        del sys.modules[m]
    from lb_worker.loop import Worker
    if Worker(ROOT, scratch='/content/work', poll_s=10).serve(idle_exit_min=1) != 'reload':
        break
    print('The app published newer code; continuing with it.')
print(f'All done in {(time.time() - started) / 60:.0f} min. Open the results in the app.')
"""),
    cell("code", """
# 4 · Give the GPU back
if RELEASE_GPU_WHEN_DONE:
    from google.colab import runtime
    print('Releasing the GPU.')
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
    # the app's own logic too: runs execute it headless on the worker (worker/lb_worker/stages/run.py)
    app_dst = root / "worker" / "app"
    shutil.rmtree(app_dst, ignore_errors=True)
    shutil.copytree(HERE / "app", app_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
