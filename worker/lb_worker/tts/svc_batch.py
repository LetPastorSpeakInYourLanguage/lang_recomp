"""Seed-VC over many files with the models loaded once (Seed-VC's inference.py reloads
them for every file), run as its own process (Seed-VC is GPL-3.0; nothing imports it):

    python svc_batch.py --seedvc <Seed-VC checkout> --model whisper --manifest m.json --out res.json [--steps 25]

manifest: [{"key", "source", "target", "out"}]: speak ``source`` in the voice of ``target``.
Timbre only (v1 models, no F0 conditioning): the source's words, rhythm and pauses stay.
"""
import argparse
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import types

ap = argparse.ArgumentParser()
ap.add_argument("--seedvc", default=".", help="the Seed-VC checkout (its modules, configs and checkpoints)")
ap.add_argument("--model", choices=["xlsr", "whisper"], required=True)
ap.add_argument("--manifest", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--steps", type=int, default=25)
ap.add_argument("--cfg", type=float, default=0.7)
a = ap.parse_args()
sys.argv = sys.argv[:1]
os.chdir(a.seedvc)  # Seed-VC reads configs/ and caches into ./checkpoints relative to itself
sys.path.insert(0, os.path.abspath("."))

# Seed-VC uses one class from dac (VectorQuantize); dac's package __init__ imports
# descript-audiotools, whose protobuf<3.20 pin broke a shared Colab session before.
# Register the packages without running their __init__, so only the quantizer loads.
_spec = importlib.util.find_spec("dac")
if _spec is None:
    raise SystemExit("pip install --no-deps descript-audio-codec")
_root = os.path.dirname(_spec.origin)
for _name, _path in (("dac", _root), ("dac.nn", os.path.join(_root, "nn"))):
    _m = types.ModuleType(_name)
    _m.__path__ = [_path]
    sys.modules[_name] = _m

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402

# torchaudio >= 2.9 saves through torchcodec, which a fresh runtime may not have
torchaudio.save = lambda path, wav, sr, **k: sf.write(path, wav.squeeze(0).cpu().numpy(), sr)
# torch >= 2.6 loads weights only by default; Seed-VC's own checkpoints (from its HF repo)
# also pickle their training state
_torch_load = torch.load
torch.load = lambda *args, **kw: _torch_load(*args, **{"weights_only": False, **kw})

import inference as I  # noqa: E402  (Seed-VC's own module)
from hf_utils import load_custom_model_from_hf  # noqa: E402

FILES = {"xlsr": ("DiT_uvit_tat_xlsr_ema.pth", "config_dit_mel_seed_uvit_xlsr_tiny.yml"),
         "whisper": ("DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth",
                     "config_dit_mel_seed_uvit_whisper_small_wavenet.yml")}
t0 = time.time()
ckpt, cfg = load_custom_model_from_hf("Plachta/Seed-VC", *FILES[a.model])
_real, _cache = I.load_models, {}


def _load_once(args):
    if "m" not in _cache:
        _cache["m"] = _real(args)
    return _cache["m"]


I.load_models = _load_once

items = json.load(open(a.manifest, encoding="utf-8"))
res = {"model": a.model, "steps": a.steps, "items": {}}
todo = [it for it in items if not os.path.exists(it["out"])]
print(f"Seed-VC {a.model}: {len(todo)} to convert ({len(items) - len(todo)} already done)", flush=True)
for n, it in enumerate(todo, 1):
    tmp = tempfile.mkdtemp()
    t = time.time()
    try:
        ns = argparse.Namespace(source=it["source"], target=it["target"], output=tmp, diffusion_steps=a.steps,
                                length_adjust=1.0, inference_cfg_rate=a.cfg, f0_condition=False,
                                auto_f0_adjust=False, semi_tone_shift=0, checkpoint=ckpt, config=cfg, fp16=True)
        with torch.no_grad():
            I.main(ns)
        (made,) = glob.glob(os.path.join(tmp, "*.wav"))
        os.makedirs(os.path.dirname(it["out"]), exist_ok=True)
        shutil.move(made, it["out"] + ".tmp.wav")
        os.replace(it["out"] + ".tmp.wav", it["out"])  # a take appears only when complete
        res["items"][it["key"]] = {"ok": True, "s": round(time.time() - t, 2)}
    except Exception as e:
        res["items"][it["key"]] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        print(f"{it['key']} failed: {e}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if n % 10 == 0 or n == len(todo):
        print(f"Seed-VC {a.model}: {n}/{len(todo)}", flush=True)
res["wall_s"] = round(time.time() - t0, 1)
with open(a.out, "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=1)
