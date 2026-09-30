"""The Lang-Bridge research runner: the heavy ML pipeline, run by hand on a GPU machine.

Use it in a notebook (notebooks/lang_bridge.ipynb: Colab, Kaggle, local Jupyter) or on a server, on your own videos, at
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
import subprocess
import sys
import tempfile
import threading
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
    """Working copies: LB_WORK (set by the notebook's setup, under its WORK_DIR), else the
    system's temporary folder."""
    base = Path(os.environ["LB_WORK"]) if os.environ.get("LB_WORK") else Path(tempfile.gettempdir()) / "lang-bridge"
    d = base / "lang-bridge-scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_links(values: list[str] | str | None) -> list[str]:
    """Links from the settings: separated by spaces or new lines; a ``.txt`` file among them
    stands for the links in it (one per line, ``#`` for comments)."""
    items = values.split() if isinstance(values, str) else list(values or [])
    out: list[str] = []
    for v in (x.strip() for x in items):
        if not v:
            continue
        if v.lower().endswith(".txt") and Path(v).expanduser().is_file():
            text = Path(v).expanduser().read_text(encoding="utf-8", errors="replace")
            out += [ln.split()[0] for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        else:
            out.append(v)
    return list(dict.fromkeys(out))


def expand_link(link: str, limit: int = 500) -> list[dict]:
    """The videos behind a link, without downloading them: one for a video, all of them
    (oldest first) for a playlist or a channel, on YouTube or any site yt-dlp knows."""
    from app import feeds

    try:
        p = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", "--no-warnings",
                            "--playlist-end", str(limit), "--", link],
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
        js = json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        js = None
    if js is None:  # not listable now: keep the link; the fetch stage reports what is wrong
        print(f"could not look up {link}; it is kept and fetched as it is", flush=True)
        return [{"id": link.rsplit("=", 1)[-1][-11:], "title": link, "url": link}]
    if js.get("_type") == "playlist" or js.get("entries") is not None:
        entries = feeds.parse(js)["entries"]
        print(f"{link}: {len(entries)} videos", flush=True)
        return list(reversed(entries))  # oldest first
    return [{"id": js.get("id") or link, "title": js.get("title") or link, "url": js.get("webpage_url") or link}]


def secret(name: str) -> str | None:
    """A setting the notebook did not fill in, from the environment (a server's HF_TOKEN).
    Tokens are typed in the notebook's settings; platform secret stores are not read."""
    return os.environ.get(name) or None


def pull_folder(bucket: str, folder: str, out: str | Path, token: str | None = None) -> Path:
    """A folder of videos kept in the bucket (``folder`` relative to the bucket's top),
    downloaded into ``out/<folder>`` (only what changed) so the run can read it."""
    rel = folder.strip().strip("/")
    dest = Path(out) / rel
    print(f"downloading {rel}/ from hf://buckets/{bucket} …", flush=True)
    Bucket(bucket, Path(out), token).pull(include=[f"{rel}/*"])
    if not dest.is_dir():
        raise SystemExit(f"no folder {rel}/ in the bucket {bucket}")
    return dest


class Bucket:
    """The output folder mirrored in a Hugging Face Storage Bucket (``namespace/name`` or
    ``namespace/name/prefix``): pulled when a run continues, pushed after every stage (in the
    background, so the GPU never waits) and at the end. The Lang-Bridge app pulls the same
    bucket to follow the run and open its results; Kaggle needs no Google Drive."""

    EXCLUDE = ["cache/*", "*.part", "*.tmp.wav", "*/tmp/*"]

    def __init__(self, name: str, root: Path, token: str | None = None, log=print):
        self.url = "hf://buckets/" + name.strip().strip("/").removeprefix("hf://buckets/")
        self.root, self.token, self.log = root, token, log
        self._lock, self._pending, self._thread = threading.Lock(), False, None

    def pull(self, include: list[str] | None = None) -> None:
        from huggingface_hub import sync_bucket

        self.root.mkdir(parents=True, exist_ok=True)
        sync_bucket(self.url, str(self.root), include=include, exclude=self.EXCLUDE, quiet=True, token=self.token)

    def push(self) -> None:
        from huggingface_hub import sync_bucket

        with self._lock:
            t = time.time()
            sync_bucket(str(self.root), self.url, exclude=self.EXCLUDE, quiet=True, token=self.token)
            self.log(f"· pushed to {self.url} ({time.time() - t:.0f} s)")

    def push_soon(self, *_) -> None:
        """Push in the background; pushes asked for meanwhile collapse into one."""
        self._pending = True
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while self._pending:
                self._pending = False
                try:
                    self.push()
                except Exception as e:  # the run goes on; the next push catches up
                    self.log(f"· push to {self.url} failed: {type(e).__name__}: {str(e)[:200]}")

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def wait(self) -> None:
        if self._thread:
            self._thread.join()


def _env(hf_token: str | None, cache: Path | None) -> None:
    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
    if cache is not None:  # models downloaded once, kept (e.g. on your Drive)
        for k, sub in {"HF_HOME": "hf", "TORCH_HOME": "torch", "LB_CACHE": ""}.items():
            os.environ.setdefault(k, str(cache / sub) if sub else str(cache))
            Path(os.environ[k]).mkdir(parents=True, exist_ok=True)


def run_manifest(run_dir: str | Path, hf_token: str | None = None, cache: str | Path | None = None,
                 bucket: str | None = None) -> dict:
    """Run a run folder (``<root>/runs/<run id>``) written by the app or by ``run_folder``.
    Media the run refers to are found relative to ``<root>``. With ``bucket``, the run is
    first pulled from it (continuing on another machine) and pushed to it as it goes."""
    from .stages.run import Run

    run_dir = Path(run_dir)
    root = run_dir.parent.parent
    hf_token = hf_token or secret("HF_TOKEN")
    _env(hf_token, Path(cache) if cache else root / "cache")
    t = time.time()
    ctx = _current["ctx"] = _Ctx(root, run_dir.name, _scratch())
    store = Bucket(bucket, root, hf_token, ctx.log) if bucket else None
    if store:
        store.pull(include=[f"runs/{run_dir.name}/*"])
        man = run_dir / "manifest.json"
        if man.exists():  # the media this run already made, wherever it made them
            works = json.loads(man.read_text(encoding="utf-8")).get("works") or []
            if works:
                store.pull(include=[f"library/{w['uid']}/*" for w in works if w.get("uid")])
        ctx.on_publish = store.push_soon
    try:
        res = Run(ctx).go()
    except BaseException:  # stopped (KeyboardInterrupt) or failed: stop its threads too
        ctx.stop()
        if store:
            store.wait()
            store.push()  # keep what was made
        raise
    if store:
        store.wait()
        store.push()
    results = sorted((run_dir / "results").glob("*.lbwork"))
    print(f"\nDone in {(time.time() - t) / 60:.0f} min: {res['videos']} videos. To look at and listen to the results, "
          f"open this in the Lang-Bridge app (Home → Open a shared work):")
    for f in results:
        print("   ", f)
    return res | {"results": [str(f) for f in results]}


def run_folder(videos: str | Path | None, output: str | Path, language: str = "en", targets: list[str] | None = None,
               stages: list[str] | None = None, links: list[str] | str | None = None, name: str | None = None,
               dub_limit: int | None = None, limit: int | None = None, takes: int = 1, captions: int = 0,
               align_captions: int = 0, align_subtitles: bool = True, hf_token: str | None = None,
               cache: str | Path | None = None, aligners: dict | None = None, options: dict | None = None,
               asr_models: dict | None = None, bucket: str | None = None, youtube: list[str] | None = None) -> dict:
    """Run the pipeline over a folder of videos and/or links; results in ``output``.

    videos     a folder (searched recursively); ``name.srt`` beside a video is its transcript
    links      links to videos, playlists or channels (YouTube or any site yt-dlp knows), or
               a .txt file of them; no folder is needed: the videos are downloaded into
               ``output`` (``youtube`` is the old name of this argument)
    stages     which of fetch, transcribe, translate, voice, mix (default: all)
    dub_limit  voice and mix only the first N videos (the rest are transcribed/translated)
    limit      take only the first N videos at all
    captions / align_captions   for YouTube videos: also take YouTube's captions for the
               first N, and force-align the first M of those, to compare with Whisper
    asr_models a recogniser per source language, e.g. {"am": "badrex/Ethio-ASR-amharic",
               "tr": "whisper"}; Whisper large-v3 otherwise (lb_worker.asr)
    aligners   a forced aligner per language, over lb_worker.asr.DEFAULT_ALIGNERS
    bucket     a Hugging Face bucket (``namespace/name[/prefix]``) the output is pushed to
    options    any other run option (app/runs.py DEFAULTS), e.g. {"asr_model": "large-v3-turbo"}
    """
    if videos and (Path(videos) / "manifest.json").exists():  # a run folder, given as the videos: continue it
        print(f"{videos} is a run folder: continuing that run")
        return run_manifest(videos, hf_token, cache, bucket)
    _repo_on_path()
    from . import asr

    hf_token = hf_token or secret("HF_TOKEN")
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
        "aligners": {**asr.DEFAULT_ALIGNERS, **settings.DEFAULTS["aligners"], **(aligners or {})}}),
        encoding="utf-8")

    links = read_links(links) + read_links(youtube)
    title = name or (Path(videos).name if videos else "Links")
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
    if links:
        from .deps import ensure

        ensure("yt-dlp", probe="yt_dlp")  # listing playlists happens before any stage installs it
        s = series.create(title, "channel", language, targets)
        for link in links:
            for e in expand_link(link):
                try:
                    pids.append(series.add_source(s["id"], e["title"][:120], e["url"], origin_id=e["id"], defer=True)["id"])
                except ValueError:  # the same video twice
                    pass
        print(f"{len(pids)} videos to work on")
    if limit:
        pids = pids[: int(limit)]
    if not pids:
        raise SystemExit("No videos found: check the folder path or the links.")
    opts = {"dub_limit": dub_limit, "takes": takes, "captions_download": captions, "captions_align": align_captions,
            "align_subtitles": align_subtitles, "asr_models": asr_models or {}} | (options or {})
    r = runs.create_for(pids, "here", stages or ALL, opts, name=title, submit=False)
    print(f"run {r['run']}: {r['videos']} videos, stages {', '.join(r['stages'])}")
    return run_manifest(r["dir"], hf_token, cache, bucket)
