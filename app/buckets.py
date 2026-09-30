"""A Hugging Face bucket as a device: a notebook (Kaggle, Colab, a server) pushes its output
folder there after every stage (lb_worker.research.Bucket); this app pulls it into a folder
on this PC, then reads it like any device folder: runs and their progress (runs.scan),
results opened by uid (runs.open_results), dubs played from the synced files.

Pulling uses this PC's Hugging Face login (`hf auth login`, or HF_TOKEN).
"""
from __future__ import annotations

import time
from pathlib import Path

from . import settings

EXCLUDE = ["cache/*", ".lb/cache/*", "*.part", "*.tmp.wav", "*/tmp/*", "*.lb-write-test"]
_last: dict[str, float] = {}


def url(root: dict) -> str:
    return "hf://buckets/" + root["bucket"]


def sync(root_id: str, update=lambda *a, **k: None) -> dict:
    """Pull the bucket into the device folder (only what changed)."""
    from huggingface_hub import sync_bucket

    r = settings.root(root_id)
    if r.get("kind") != "bucket":
        raise ValueError(f"{r['name']} is not a Hugging Face bucket")
    dest = Path(r["path"])
    dest.mkdir(parents=True, exist_ok=True)
    t = time.time()
    update(None, f"pulling {r['bucket']}")
    plan = sync_bucket(url(r), str(dest), exclude=EXCLUDE, quiet=True)
    _last[root_id] = time.time()
    n = len(getattr(plan, "operations", None) or []) if plan is not None else None
    return {"root": root_id, "seconds": round(time.time() - t, 1), "changed": n}


def last_sync(root_id: str) -> float | None:
    return _last.get(root_id)
