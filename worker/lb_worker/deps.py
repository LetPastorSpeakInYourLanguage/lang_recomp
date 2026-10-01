"""Per-session lazy installs: a stage installs what it needs the first time it runs,
so a session that only pings never pays for torch-heavy packages."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_done: set[str] = set()


def cache_dir(name: str) -> Path:
    """Persistent per-tool cache on Drive (LB_CACHE, set by the notebook); falls
    back to local disk when run elsewhere."""
    p = Path(os.environ.get("LB_CACHE", Path.home() / ".langbridge_cache")) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def yt_cookies() -> list[str]:
    """yt-dlp's ``--cookies`` when the person gave a YouTube cookies file (YT_COOKIES in the
    notebook, ``LB_YT_COOKIES`` in the environment): YouTube asks Colab's and Kaggle's
    addresses to sign in. yt-dlp writes refreshed cookies back to its file, so it gets a
    private copy and the person's file is never changed."""
    src = os.environ.get("LB_YT_COOKIES", "").strip()
    if not src or not Path(src).is_file():
        return []
    local = Path(tempfile.gettempdir()) / "lb_yt_cookies.txt"
    if not local.exists():
        shutil.copyfile(src, local)
    return ["--cookies", str(local)]


SIGN_IN_HINT = ("YouTube asks this machine to sign in (Colab and Kaggle addresses often are): set YT_COOKIES "
                "in the notebook to a cookies file exported from your browser (notebooks/README.md), or put "
                "the videos in the workspace folder")


def ensure(*pip_specs: str, probe: str | None = None) -> None:
    """pip install the specs once per session. ``probe`` is a module that, if already
    importable, means nothing needs installing (Colab ships many packages)."""
    key = " ".join(pip_specs)
    if key in _done:
        return
    if probe:
        try:
            importlib.import_module(probe)
            _done.add(key)
            return
        except ImportError:
            pass
    print(f"pip install {key}", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pip_specs], check=True)
    importlib.invalidate_caches()
    _done.add(key)


class _NotRetryable(Exception):
    def __init__(self, response):
        self.response = response
        super().__init__(f"HTTP {response.status_code} for {response.url}")


def fetch(url: str, dest: str | Path, log=print, tries: int = 12) -> Path:
    """Download with resume and retries, for slow or flaky links.

    Bytes land in ``dest.part`` and are renamed only when complete, so a dropped
    connection can never leave a truncated file under the final name. A file already
    at ``dest`` that is shorter than the server's copy (left by a downloader
    without this guard) is resumed rather than trusted.
    """
    import time

    import requests

    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    try:
        head = requests.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException as e:
        if dest.exists() and dest.stat().st_size > 0:  # offline or slow network: keep the file we have
            log(f"{dest.name}: could not check its size online ({type(e).__name__}); using the copy on disk")
            return dest
        raise
    total = int(head.headers.get("Content-Length") or 0)
    if dest.exists():
        if total and dest.stat().st_size >= total:
            return dest
        log(f"{dest.name}: existing file is incomplete ({dest.stat().st_size}/{total} bytes); resuming")
        dest.replace(part)
    for attempt in range(tries):
        have = part.stat().st_size if part.exists() else 0
        if total and have >= total:
            break
        try:
            hdr = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(url, headers=hdr, stream=True, timeout=60, allow_redirects=True) as r:
                if have and r.status_code != 206:  # server ignored the range: start over
                    have = 0
                    part.unlink(missing_ok=True)
                if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                    # Not there (callers such as audio-separator probe URLs that may
                    # 404 on purpose): retrying cannot help.
                    part.unlink(missing_ok=True)
                    raise _NotRetryable(r)
                r.raise_for_status()
                last = time.time()
                with open(part, "ab") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
                        if time.time() - last > 30:
                            log(f"{dest.name}: {have / 2**20:.0f}/{total / 2**20:.0f} MB")
                            last = time.time()
            if not total or have >= total:
                break
        except _NotRetryable as e:
            # Surface it the way requests would, so callers' own handling still works.
            raise requests.HTTPError(str(e), response=e.response) from None
        except (requests.RequestException, OSError) as e:
            wait = min(60, 5 * (attempt + 1))
            log(f"{dest.name}: {type(e).__name__} at {have / 2**20:.0f} MB; retry in {wait}s")
            time.sleep(wait)
    else:
        raise RuntimeError(f"{dest.name}: download did not complete after {tries} attempts")
    part.replace(dest)
    log(f"{dest.name}: complete ({dest.stat().st_size / 2**20:.0f} MB)")
    return dest


def hf_snapshot(repo_id: str, log=print, tries: int = 8, **kw) -> str:
    """snapshot_download with retries; huggingface_hub resumes partial files itself."""
    import time

    from huggingface_hub import snapshot_download

    for attempt in range(tries):
        try:
            return snapshot_download(repo_id, **kw)
        except Exception as e:  # network errors surface as several different types
            if attempt == tries - 1:
                raise
            wait = min(60, 5 * (attempt + 1))
            log(f"{repo_id}: {type(e).__name__}: {str(e)[:120]}; retry in {wait}s")
            time.sleep(wait)
    raise AssertionError


def gpu_count() -> int:
    """CUDA GPUs on this machine (Kaggle's T4 ×2: 2)."""
    try:
        import torch

        return torch.cuda.device_count() if torch.cuda.is_available() else 0
    except ImportError:
        return 0


def device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
