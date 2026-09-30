"""App settings: which job folders exist, and which one new work goes to.

A job folder is a root the job-bundle protocol runs in. "colab" folders are on
Google Drive: runs there are only prepared, and a person runs them with
notebooks/lang_bridge.ipynb (RUN_FOLDER); "folder" is any folder on this PC a notebook
writes its results into (a local Jupyter's OUTPUT, a copied Kaggle output): read only for
runs, nobody watches it; "local" folders are on this PC and
served by Local-Worker.cmd. Every job row remembers its folder, so switching the
active folder never loses track of work already submitted elsewhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .db import DATA

PATH = DATA / "settings.json"
# colab: a Drive folder a notebook works in · local: this PC's worker · bucket: a Hugging Face
# bucket a notebook (Kaggle, Colab, a server) pushes to; "path" is where it is synced on this PC ·
# folder: a results folder on this PC that a notebook wrote (runs are read, never queued)
KINDS = ("colab", "local", "bucket", "folder")
NOTEBOOK_KINDS = ("colab", "bucket", "folder")  # run by hand in a notebook: runs are prepared, never queued

DEFAULTS = {
    "roots": [
        {"id": "colab", "name": "Colab GPU (Google Drive)", "kind": "colab", "path": "G:/My Drive/LangBridge"},
        {"id": "local", "name": "This PC (Arc GPU + CPU)", "kind": "local", "path": "D:/LangBridgeLocal"},
    ],
    "active": "colab",
    # Forced-alignment model per language: any Hugging Face CTC model with a
    # character vocabulary (vet one in Settings before adding it).
    "aligners": {"en": "facebook/wav2vec2-base-960h", "am": "badrex/Ethio-ASR-amharic"},
}


def load() -> dict:
    try:
        s = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        s = {}
    out = {**DEFAULTS, **s}
    out["aligners"] = s["aligners"] if isinstance(s.get("aligners"), dict) else dict(DEFAULTS["aligners"])
    if not isinstance(s.get("keep_words"), list):
        from .interjections import DEFAULT_KEEP_WORDS

        out["keep_words"] = list(DEFAULT_KEEP_WORDS)
    if not out["roots"]:
        out["roots"] = DEFAULTS["roots"]
    if out["active"] not in {r["id"] for r in out["roots"]}:
        out["active"] = out["roots"][0]["id"]
    return out


def save(s: dict) -> dict:
    roots = []
    seen = set()
    for r in s.get("roots", []):
        name = str(r.get("name", "")).strip() or "Job folder"
        path = str(r.get("path", "")).strip()
        kind = r.get("kind") if r.get("kind") in KINDS else "local"
        bucket = str(r.get("bucket", "")).strip().removeprefix("hf://buckets/").strip("/")
        if not path or (kind == "bucket" and bucket.count("/") < 1):
            continue
        rid = str(r.get("id") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "folder")
        while rid in seen:
            rid += "-2"
        seen.add(rid)
        roots.append({"id": rid, "name": name, "kind": kind, "path": path} | ({"bucket": bucket} if kind == "bucket" else {}))
    if not roots:
        raise ValueError("at least one job folder is required")
    active = s.get("active") if s.get("active") in seen else roots[0]["id"]
    aligners = {str(k).strip().lower(): str(v).strip() for k, v in (s.get("aligners") or load()["aligners"]).items()
                if str(k).strip() and str(v).strip()}
    keep = s.get("keep_words")
    if not isinstance(keep, list):
        keep = load()["keep_words"]
    out = {"roots": roots, "active": active, "aligners": aligners,
           "keep_words": sorted({str(w).strip().lower() for w in keep if str(w).strip()})}
    DATA.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def root(rid: str | None = None) -> dict:
    s = load()
    rid = rid or s["active"]
    return next((r for r in s["roots"] if r["id"] == rid), s["roots"][0])


def aligner(language: str) -> str | None:
    return load()["aligners"].get(language)


def local_root() -> Path | None:
    r = next((r for r in load()["roots"] if r["kind"] == "local"), None)
    return Path(r["path"]) if r else None
