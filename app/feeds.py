"""List the videos of a YouTube channel or playlist, without downloading any.

`yt-dlp --flat-playlist -J` returns a playlist; a channel URL comes back as nested
tab playlists ("<channel> - Videos", "- Live", "- Shorts"), each holding its entries.
`parse` flattens that into one list and keeps the tab as the entry's section. Flat
listings carry no upload date; order follows the channel (newest first).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


def parse(js: dict) -> dict:
    seen: set[str] = set()
    out: list[dict] = []

    def walk(node: dict, section: str | None) -> None:
        for e in node.get("entries") or []:
            if not isinstance(e, dict):
                continue
            if e.get("entries") is not None or e.get("_type") == "playlist":
                title = e.get("title") or ""
                walk(e, title.rsplit(" - ", 1)[-1] if " - " in title else (title or section))
                continue
            vid = e.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append({"id": vid, "title": e.get("title") or vid,
                        "url": e.get("url") or f"https://www.youtube.com/watch?v={vid}",
                        "duration": e.get("duration"), "section": section or "Videos",
                        "live": e.get("live_status") in ("is_live", "is_upcoming")})

    walk(js, None)
    return {"title": js.get("title") or js.get("channel") or "", "channel": js.get("channel") or js.get("uploader"),
            "entries": out}


def listing(url: str, limit: int = 100) -> dict:
    """The newest ``limit`` videos per tab of a channel or playlist."""
    # as a module of this Python (a notebook has no yt-dlp command); node for YouTube where present
    js = ["--js-runtimes", "node"] if shutil.which("node") else []
    p = subprocess.run([sys.executable, "-m", "yt_dlp", *js, "--flat-playlist", "-J", "--playlist-end", str(limit),
                        "--", url], capture_output=True, text=True, encoding="utf-8", timeout=180)
    if p.returncode:
        raise RuntimeError(f"yt-dlp could not list {url}: {p.stderr.strip()[-300:]}")
    return parse(json.loads(p.stdout))
