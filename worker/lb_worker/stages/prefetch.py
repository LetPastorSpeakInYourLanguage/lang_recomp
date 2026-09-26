"""Download models ahead of time, one at a time, with resume and retries.

On a slow or flaky link it is far better to fetch models deliberately (and see the
progress) than to have the first real job stall on a multi-gigabyte download.

params: {"separator": [model filenames] | ["default"], "whisper": [sizes],
         "hf": [repo ids]}
"""
from __future__ import annotations

import time

from ..deps import cache_dir, ensure, hf_snapshot
from ..registry import stage


@stage("prefetch", model_key="prefetch")
def prefetch(ctx) -> dict:
    p = ctx.params
    todo = [("separator", m) for m in p.get("separator", [])] + \
           [("whisper", m) for m in p.get("whisper", [])] + [("hf", m) for m in p.get("hf", [])]
    done = {}
    for i, (kind, name) in enumerate(todo):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.set_progress(i / max(1, len(todo)), f"{kind}: {name}")
        t = time.time()
        if kind == "separator":
            ensure("audio-separator[cpu]", probe="audio_separator")
            ensure("audioread", probe="audioread")
            from audio_separator.separator import Separator

            from .analysis import patch_separator_download

            patch_separator_download(ctx.log)
            sep = Separator(output_dir=str(ctx.work), model_file_dir=str(cache_dir("audio-separator")))
            sep.load_model() if name == "default" else sep.load_model(name)
        elif kind == "whisper":
            ensure("faster-whisper>=1.1", probe="faster_whisper")
            from .analysis import whisper_path

            whisper_path(name, ctx.log)
        else:
            hf_snapshot(name, log=ctx.log)
        done[f"{kind}:{name}"] = round(time.time() - t, 1)
        ctx.log(f"ready: {kind} {name} ({done[f'{kind}:{name}']}s)")
        ctx.flush_log()
    return done
