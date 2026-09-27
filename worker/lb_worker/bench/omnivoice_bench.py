"""OmniVoice takes per call: the same texts at several batch sizes, one reused voice prompt.
Run as its own process by lb_worker.bench.gpu.bench_omnivoice.

    python omnivoice_bench.py --ref ref.wav [--ref-text "…"] --texts '["…"]' --batches 1,4,8,16 --out r.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

try:
    from omnivoice import OmniVoiceGenerationConfig
except ImportError:
    OmniVoiceGenerationConfig = None

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # …/worker, for lb_worker.bench.common
from lb_worker.bench.common import GpuSampler  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ref", required=True)
ap.add_argument("--ref-text", default=None)
ap.add_argument("--texts", required=True)
ap.add_argument("--batches", default="1,4,8,16")
ap.add_argument("--steps", type=int, default=16)
ap.add_argument("--language", default="Amharic")
ap.add_argument("--model", default="k2-fsa/OmniVoice")
ap.add_argument("--out", required=True)
ap.add_argument("--wavs", default=None, help="keep the first batch size's takes here, to listen to")
a = ap.parse_args()

if torch.cuda.is_available():
    dev, acc = "cuda:0", torch.cuda
elif hasattr(torch, "xpu") and torch.xpu.is_available():  # Intel Arc
    dev, acc = "xpu", torch.xpu
else:
    dev, acc = "cpu", None
t0 = time.time()
model = OmniVoice.from_pretrained(a.model, device_map=dev, dtype=torch.float16 if dev != "cpu" else torch.float32)
load_s = time.time() - t0
prompt = model.create_voice_clone_prompt(ref_audio=a.ref, ref_text=a.ref_text)  # made once, reused by every take
texts = json.loads(a.texts)
cfg = {"generation_config": OmniVoiceGenerationConfig(num_step=a.steps, guidance_scale=2.0)} if OmniVoiceGenerationConfig else {}
print(f"model loaded in {load_s:.0f} s on {dev}; {len(texts)} takes per batch size", flush=True)

model.generate(text=texts[:1], language=a.language, voice_clone_prompt=[prompt], **cfg)  # warm-up
rows = []
for bs in [int(x) for x in a.batches.split(",")]:
    if acc:
        acc.reset_peak_memory_stats()
    audio_s, failed = 0.0, 0
    with GpuSampler() as g:
        for i in range(0, len(texts), bs):
            chunk = texts[i:i + bs]
            try:
                outs = model.generate(text=chunk, language=[a.language] * len(chunk),
                                      voice_clone_prompt=[prompt] * len(chunk), **cfg)
            except Exception as e:  # e.g. out of memory at a large batch
                print(f"batch {bs}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                failed += len(chunk)
                if acc:
                    acc.empty_cache()
                continue
            for k, x in enumerate(outs):
                audio_s += len(x) / 24000
                if a.wavs and bs == int(a.batches.split(",")[0]):
                    Path(a.wavs).mkdir(parents=True, exist_ok=True)
                    sf.write(Path(a.wavs) / f"take_{i + k:02d}.wav", np.asarray(x), 24000)
    gpu0 = next(iter(g.stats().values()), {})
    row = {"batch": bs, "s": round(g.seconds, 1), "takes_per_min": round((len(texts) - failed) / g.seconds * 60, 1),
           "audio_x_realtime": round(audio_s / g.seconds, 2), "gpu_util": gpu0.get("util_mean"),
           "gpu_mem_gb": gpu0.get("mem_max_gb"),
           "torch_peak_gb": round(acc.max_memory_allocated() / 2**30, 2) if acc else None,
           "failed": failed}
    rows.append(row)
    print(json.dumps(row), flush=True)

Path(a.out).write_text(json.dumps({"load_s": round(load_s, 1), "steps": a.steps, "texts": len(texts), "rows": rows},
                                  indent=1), encoding="utf-8")
