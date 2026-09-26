"""OmniVoice batch generation, run as its own process by the bakeoff stage.

    python omnivoice_gen.py --model k2-fsa/OmniVoice --manifest m.json --out results.json

manifest: [{"key", "text", "ref_audio", "ref_text"?, "duration"?, "out"}]
"""
import argparse
import json
import os
import time
import traceback

import soundfile as sf
import torch
from omnivoice import OmniVoice

try:
    from omnivoice import OmniVoiceGenerationConfig
except ImportError:  # older/newer package layouts
    OmniVoiceGenerationConfig = None

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--manifest", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--language", default="Amharic")
ap.add_argument("--steps", type=int, default=32)
ap.add_argument("--speed", type=float, default=None, help="speaking-rate factor when no duration is set")
a = ap.parse_args()

# CUDA (Colab) > Intel XPU (Arc iGPU, if this torch build has it) > CPU. Half
# precision only on a GPU; CPUs are slower and less accurate in fp16.
if torch.cuda.is_available():
    dev, dtype = "cuda:0", torch.float16
elif hasattr(torch, "xpu") and torch.xpu.is_available():
    dev, dtype = "xpu", torch.float16
else:
    dev, dtype = "cpu", torch.float32
    torch.set_num_threads(max(1, (os.cpu_count() or 2) - 2))
print("device", dev, flush=True)

t0 = time.time()
model = OmniVoice.from_pretrained(a.model, device_map=dev, dtype=dtype)
load_s = time.time() - t0
class Progress:
    """A line every 30 s (and at the end): how many done, how fast, how long is left."""

    def __init__(self, what, total):
        self.what, self.total, self.done, self.failed = what, total, 0, 0
        self.t0 = self.last = time.time()

    def step(self, ok=True, force=False):
        self.done += 1
        self.failed += 0 if ok else 1
        now = time.time()
        if force or now - self.last >= 30 or self.done == self.total:
            self.last = now
            per = (now - self.t0) / max(1, self.done)
            left = per * (self.total - self.done) / 60
            print(f"{self.what} {self.done}/{self.total} ({100 * self.done // max(1, self.total)}%) · "
                  f"{per:.1f} s each · about {left:.0f} min left" + (f" · {self.failed} failed" if self.failed else ""),
                  flush=True)

items = json.load(open(a.manifest, encoding="utf-8"))
results = {"model": a.model, "load_s": round(load_s, 1), "items": {}}
if dev.startswith("cuda"):
    torch.cuda.reset_peak_memory_stats()
todo = sum(1 for it in items if not (it.get("skip_existing") and os.path.exists(it["out"])))
print(f"model loaded in {load_s:.0f} s; {todo} takes to make ({len(items) - todo} already made)", flush=True)
bar = Progress("voiced", todo)

for it in items:
    if it.get("skip_existing") and os.path.exists(it["out"]):
        results["items"][it["key"]] = {"ok": True, "resumed": True}
        continue
    t = time.time()
    if it.get("seed") is not None:  # distinct, reproducible takes
        torch.manual_seed(int(it["seed"]))
    try:
        kw = {"text": it["text"], "ref_audio": it["ref_audio"]}
        if it.get("ref_text"):
            kw["ref_text"] = it["ref_text"]
        if it.get("duration"):
            kw["duration"] = float(it["duration"])
        elif it.get("speed") or a.speed:
            kw["speed"] = float(it.get("speed") or a.speed)
        if OmniVoiceGenerationConfig is not None:
            kw["generation_config"] = OmniVoiceGenerationConfig(num_step=a.steps, guidance_scale=2.0)
        try:
            audio = model.generate(language=a.language, **kw)
        except TypeError:  # this build has no language kwarg
            audio = model.generate(**kw)
        tmp = it["out"] + ".tmp.wav"
        sf.write(tmp, audio[0], 24000)
        os.replace(tmp, it["out"])  # a take appears only when complete
        results["items"][it["key"]] = {"ok": True, "gen_s": round(time.time() - t, 2)}
    except Exception as e:
        results["items"][it["key"]] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                                       "trace": traceback.format_exc()[-800:]}
    r = results["items"][it["key"]]
    if not r["ok"]:
        print(f"take {it['key']} failed: {r['error'][:200]}", flush=True)
    bar.step(r["ok"])

results["device"] = dev
if dev.startswith("cuda"):
    results["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
with open(a.out, "w", encoding="utf-8") as fh:  # closed (flushed) before os._exit below
    json.dump(results, fh, indent=1)
# Exit without interpreter teardown: on Windows the Intel XPU runtime can hang for
# minutes while shutting down, after all the work is saved.
import sys as _sys
_sys.stdout.flush()
_sys.stderr.flush()
os._exit(0)
