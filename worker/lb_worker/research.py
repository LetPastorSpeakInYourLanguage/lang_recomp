"""The Lang-Bridge research runner: the heavy ML pipeline, run by hand on a GPU machine.

Use it in a notebook (colab/lang_bridge.ipynb) or on a server, on your own videos, at
your own discretion — no app, no queue:

    from lb_worker.research import run_folder, run_manifest
    run_folder("/content/drive/MyDrive/Teachings", "/content/drive/MyDrive/lb-output",
               language="en", targets=["am"], dub_limit=3, hf_token="hf_…")

Input: a folder of videos (any layout; docs/LIBRARY_FOLDERS.md describes the one that
works best, with ``name.srt`` subtitles used instead of transcribing), and/or YouTube
video or playlist links. Stages, in order: fetch, transcribe, translate, voice, mix —
run all or some (e.g. ``stages=["fetch", "transcribe"]`` for transcripts only).

Output, in the output folder:

    library/<work>/<video>/   video (for links), stems, transcript files, takes, mixes,
                              the dubbed MP4s and subtitles
    runs/<run>/results/*.lbwork   the work, ready to open in the Lang-Bridge app
                                  (Home → Open a shared work): media are referenced where
                                  they are, nothing is copied
    runs/<run>/report.json    timings, and YouTube captions vs Whisper when asked for

A run that stops (a closed notebook, a lost GPU) continues where it was when started
again with the same arguments. The app can also prepare a run folder for you; run it
with ``run_manifest(folder)``.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ALL = ["fetch", "transcribe", "translate", "voice", "mix"]
_current: dict = {}  # the run in progress in this Python process


class _Ctx:
    """What a pipeline stage needs from its surroundings, without any job queue."""

    def __init__(self, root: Path, run_id: str, scratch: Path):
        self.params = {"run": run_id}
        self.layout = type("Layout", (), {"root": root})()
        self.worker = type("Machine", (), {"scratch": scratch, "_models": {}})()
        self.work = scratch / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        self.progress = 0.0
        self.log_file = root / "runs" / run_id / "log.txt"

    def model(self, key, loader):
        if key not in self.worker._models:
            self.worker._models[key] = loader()
        return self.worker._models[key]

    prints = True

    def log(self, msg: str) -> None:
        """Printed in the notebook, and kept in runs/<run>/log.txt (readable from your PC)."""
        print(msg, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def stop(self) -> None:
        self.stopped = True

    def set_progress(self, frac: float, note: str | None = None) -> None:
        self.progress = frac

    def checkpoint(self) -> None:
        pass

    def cancelled(self) -> bool:
        # a run stopped by hand, or replaced by a newer one in the same notebook: its
        # background download thread must not keep writing into the same folder
        return getattr(self, "stopped", False) or _current.get("ctx") is not self


def _repo_on_path() -> None:
    here = Path(__file__).resolve()
    for p in (here.parents[2], here.parents[1]):  # the repo (…/worker/lb_worker) or a copy beside app/
        if (p / "app" / "__init__.py").exists() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _scratch() -> Path:
    base = Path("/content") if Path("/content").exists() else Path(tempfile.gettempdir())
    d = base / "lang-bridge-scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env(hf_token: str | None, cache: Path | None) -> None:
    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
    if cache is not None:  # models downloaded once, kept (e.g. on your Drive)
        for k, sub in {"HF_HOME": "hf", "TORCH_HOME": "torch", "LB_CACHE": ""}.items():
            os.environ.setdefault(k, str(cache / sub) if sub else str(cache))
            Path(os.environ[k]).mkdir(parents=True, exist_ok=True)


def run_manifest(run_dir: str | Path, hf_token: str | None = None, cache: str | Path | None = None) -> dict:
    """Run a run folder (``<root>/runs/<run id>``) written by the app or by ``run_folder``.
    Media the run refers to are found relative to ``<root>``."""
    from .stages.run import Run

    run_dir = Path(run_dir)
    root = run_dir.parent.parent
    _env(hf_token, Path(cache) if cache else root / "cache")
    t = time.time()
    ctx = _current["ctx"] = _Ctx(root, run_dir.name, _scratch())
    try:
        res = Run(ctx).go()
    except BaseException:  # stopped (KeyboardInterrupt) or failed: stop its threads too
        ctx.stop()
        raise
    results = sorted((run_dir / "results").glob("*.lbwork"))
    print(f"\nDone in {(time.time() - t) / 60:.0f} min: {res['videos']} videos. To look at and listen to the results, "
          f"open this in the Lang-Bridge app (Home → Open a shared work):")
    for f in results:
        print("   ", f)
    return res | {"results": [str(f) for f in results]}


def run_folder(videos: str | Path | None, output: str | Path, language: str = "en", targets: list[str] | None = None,
               stages: list[str] | None = None, youtube: list[str] | None = None, name: str | None = None,
               dub_limit: int | None = None, limit: int | None = None, takes: int = 1, captions: int = 0,
               align_captions: int = 0, align_subtitles: bool = True, hf_token: str | None = None,
               cache: str | Path | None = None, aligners: dict | None = None, options: dict | None = None) -> dict:
    """Run the pipeline over a folder of videos and/or YouTube links; results in ``output``.

    videos     a folder (searched recursively); ``name.srt`` beside a video is its transcript
    youtube    video or playlist links (downloaded into ``output``)
    stages     which of fetch, transcribe, translate, voice, mix (default: all)
    dub_limit  voice and mix only the first N videos (the rest are transcribed/translated)
    limit      take only the first N videos at all
    captions / align_captions   for YouTube videos: also take YouTube's captions for the
               first N, and force-align the first M of those, to compare with Whisper
    options    any other run option (app/runs.py DEFAULTS), e.g. {"asr_model": "large-v3-turbo"}
    """
    if videos and (Path(videos) / "manifest.json").exists():  # a run folder, given as the videos: continue it
        print(f"{videos} is a run folder: continuing that run")
        return run_manifest(videos, hf_token, cache)
    _repo_on_path()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    _env(hf_token, Path(cache) if cache else out / "cache")
    targets = targets or ["am"]
    lib = _scratch() / "catalogue"  # a throwaway catalogue; the run itself rebuilds its own
    shutil.rmtree(lib, ignore_errors=True)
    lib.mkdir(parents=True)
    os.environ["LANGBRIDGE_DATA"] = str(lib)
    from app import db, feeds, libraries, runs, series, settings

    db.DATA, db.DB_PATH, settings.PATH = lib, lib / "langbridge.db", lib / "settings.json"
    db._local.c = None
    settings.PATH.write_text(json.dumps({
        "roots": [{"id": "here", "name": "this machine", "kind": "local", "path": str(out.resolve())}], "active": "here",
        "aligners": aligners or settings.DEFAULTS["aligners"]}), encoding="utf-8")

    title = name or (Path(videos).name if videos else "YouTube")
    pids: list[str] = []
    if videos:
        folder = Path(videos)
        nested = any(p.is_dir() and any(q.suffix.lower() in libraries.MEDIA for q in p.rglob("*")) for p in folder.iterdir())
        if nested:  # works in subfolders: the library rules (docs/LIBRARY_FOLDERS.md)
            L = libraries.create(title, "here", str(folder), language, targets)
            found = libraries.scan(L["id"])
            print(f"{found['videos']} videos in {found['works']} works found in {folder}")
            pids += [v["id"] for w in libraries.tree(L["id"]) for v in w["videos"]]
        else:  # a flat folder of episodes is one work
            s = series.create(title, "other", language, targets)
            pids += runs.folder_sources(s["id"], str(folder), "here")
            print(f"{len(pids)} videos found in {folder}")
    if youtube:
        from .deps import ensure

        ensure("yt-dlp", probe="yt_dlp")  # listing playlists happens before any stage installs it
        s = series.create(title, "channel", language, targets)
        for link in youtube:
            link = link.strip()
            if not link:
                continue
            entries = feeds.listing(link, 500)["entries"] if ("list=" in link or "/@" in link or "/channel/" in link) \
                else [{"id": link.rsplit("=", 1)[-1][-11:], "title": link, "url": link}]
            for e in reversed(entries):  # oldest first
                try:
                    pids.append(series.add_source(s["id"], e["title"][:120], e["url"], origin_id=e["id"], defer=True)["id"])
                except ValueError:
                    pass
        print(f"{len(pids)} videos to work on")
    if limit:
        pids = pids[: int(limit)]
    if not pids:
        raise SystemExit("No videos found: check the folder path or the links.")
    opts = {"dub_limit": dub_limit, "takes": takes, "captions_download": captions, "captions_align": align_captions,
            "align_subtitles": align_subtitles} | (options or {})
    r = runs.create_for(pids, "here", stages or ALL, opts, name=title, submit=False)
    print(f"run {r['run']}: {r['videos']} videos, stages {', '.join(r['stages'])}")
    return run_manifest(r["dir"], hf_token, cache)
