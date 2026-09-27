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
ap.add_argument("--batch", type=int, default=1, help="takes per generate() call (GPU fill; the bench picks it)")
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

prompts = {}  # one voice prompt per reference, made once and reused by every take


def prompt_for(it):
    key = (it["ref_audio"], it.get("ref_text") or "")
    if key not in prompts:
        make = getattr(model, "create_voice_clone_prompt", None)
        prompts[key] = make(ref_audio=it["ref_audio"], ref_text=it.get("ref_text")) if make else None
    return prompts[key]


def generate(batch):
    """Takes for a batch of items in one call (the GPU fills up); lists per item."""
    kw = {"text": [it["text"] for it in batch]}
    p = [prompt_for(it) for it in batch]
    if all(x is not None for x in p):
        kw["voice_clone_prompt"] = p
    else:  # an older build without reusable prompts
        kw["ref_audio"] = [it["ref_audio"] for it in batch]
        if all(it.get("ref_text") for it in batch):
            kw["ref_text"] = [it["ref_text"] for it in batch]
    if any(it.get("duration") for it in batch):
        kw["duration"] = [float(it["duration"]) if it.get("duration") else None for it in batch]
    if any(it.get("speed") for it in batch) or a.speed:
        kw["speed"] = [None if it.get("duration") else float(it.get("speed") or a.speed or 1.0) for it in batch]
    if OmniVoiceGenerationConfig is not None:
        kw["generation_config"] = OmniVoiceGenerationConfig(num_step=a.steps, guidance_scale=2.0)
    if batch[0].get("seed") is not None:  # reproducible takes (per batch)
        torch.manual_seed(int(batch[0]["seed"]))
    try:
        return model.generate(language=[a.language] * len(batch), **kw)
    except TypeError:  # this build has no language kwarg
        return model.generate(**kw)


def save(it, audio, t):
    tmp = it["out"] + ".tmp.wav"
    sf.write(tmp, audio, 24000)
    os.replace(tmp, it["out"])  # a take appears only when complete
    results["items"][it["key"]] = {"ok": True, "gen_s": round(t, 2)}


todo_items = []
for it in items:
    if it.get("skip_existing") and os.path.exists(it["out"]):
        results["items"][it["key"]] = {"ok": True, "resumed": True}
    else:
        todo_items.append(it)
todo_items.sort(key=lambda it: (it["ref_audio"], it.get("ref_text") or ""))  # same voice together
for i in range(0, len(todo_items), max(1, a.batch)):
    batch = todo_items[i:i + max(1, a.batch)]
    t = time.time()
    try:
        outs = generate(batch)
        for it, audio in zip(batch, outs):
            save(it, audio, (time.time() - t) / len(batch))
    except Exception:  # retry one by one, so one bad line does not fail its neighbours
        for it in batch:
            t1 = time.time()
            try:
                save(it, generate([it])[0], time.time() - t1)
            except Exception as e:
                results["items"][it["key"]] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                                               "trace": traceback.format_exc()[-800:]}
        if dev.startswith("cuda"):
            torch.cuda.empty_cache()
    for it in batch:
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
