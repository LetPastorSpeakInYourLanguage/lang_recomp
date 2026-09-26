"""Objective scores for bake-off outputs, run as its own process.

    python score.py --manifest score.json --out scores.json

manifest: {"speakers": {spk: [heldout wav, ...]},
           "items": [{"key", "wav", "speaker", "text", "slot_s", "source_wav"}]}

  sim      cosine(WavLM-SV x-vector of output, centroid of the speaker's held-out clips)
  cer      character error rate of a CTC back-transcription against the intended text
           (any language's CTC model via --asr; "--asr none" skips it)
  dur      output seconds / source slot seconds
  av_dist  distance in (arousal, valence) between the source clip and the output
"""
import argparse
import json
import os
import time
import unicodedata

import numpy as np
import soundfile as sf
import torch
import torchaudio

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--asr", default="badrex/Ethio-ASR-amharic")
ap.add_argument("--no-emotion", action="store_true")
a = ap.parse_args()
m = json.load(open(a.manifest, encoding="utf-8"))
dev = "cuda" if torch.cuda.is_available() else ("xpu" if hasattr(torch, "xpu") and torch.xpu.is_available() else "cpu")


def load16(path):
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    x = torch.from_numpy(x.mean(1))
    if sr != 16000:
        x = torchaudio.functional.resample(x, sr, 16000)
    return x


# ---- speaker similarity ------------------------------------------------------------------
from transformers import AutoFeatureExtractor, WavLMForXVector  # noqa: E402

fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv")
sv = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv").to(dev).eval()


@torch.no_grad()
def xvec(path):
    inp = fe(load16(path).numpy(), sampling_rate=16000, return_tensors="pt").to(dev)
    e = sv(**inp).embeddings[0]
    return torch.nn.functional.normalize(e, dim=-1).cpu()


centroids = {}
for spk, wavs in m["speakers"].items():
    c = torch.stack([xvec(w) for w in wavs]).mean(0)
    centroids[spk] = torch.nn.functional.normalize(c, dim=-1)

# ---- back-transcription (the language's CTC model) ----------------------------------------
from transformers import AutoModelForCTC, AutoProcessor  # noqa: E402

proc = ctc = None
if a.asr and a.asr.lower() != "none":
    proc = AutoProcessor.from_pretrained(a.asr)
    ctc = AutoModelForCTC.from_pretrained(a.asr).to(dev).eval()


@torch.no_grad()
def transcribe(path):
    inp = proc(load16(path).numpy(), sampling_rate=16000, return_tensors="pt").to(dev)
    ids = ctc(**inp).logits.argmax(-1)
    return proc.batch_decode(ids)[0]


def norm_am(s):
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch for ch in s if not (0x1360 <= ord(ch) <= 0x1368) and ch not in ",.?!:;\"'()")
    return " ".join(s.split())


def cer(ref, hyp):
    r, h = list(norm_am(ref).replace(" ", "")), list(norm_am(hyp).replace(" ", ""))
    d = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hc in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rc != hc))
    return d[len(h)] / max(1, len(r))


# ---- arousal / valence --------------------------------------------------------------------
av_model = None
try:
    if a.no_emotion:
        raise RuntimeError("skipped (--no-emotion)")
    from transformers import Wav2Vec2Processor  # noqa: E402
    from transformers.models.wav2vec2.modeling_wav2vec2 import (  # noqa: E402
        Wav2Vec2Model, Wav2Vec2PreTrainedModel)

    class RegressionHead(torch.nn.Module):
        def __init__(self, config):
            super().__init__()
            self.dense = torch.nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = torch.nn.Dropout(config.final_dropout)
            self.out_proj = torch.nn.Linear(config.hidden_size, config.num_labels)

        def forward(self, x):
            return self.out_proj(self.dropout(torch.tanh(self.dense(self.dropout(x)))))

    class EmotionModel(Wav2Vec2PreTrainedModel):
        def __init__(self, config):
            super().__init__(config)
            self.wav2vec2 = Wav2Vec2Model(config)
            self.classifier = RegressionHead(config)
            self.post_init()  # init_weights() alone breaks on current transformers

        def forward(self, input_values):
            h = self.wav2vec2(input_values)[0].mean(dim=1)
            return self.classifier(h)  # arousal, dominance, valence in ~[0, 1]

    AV = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
    av_proc = Wav2Vec2Processor.from_pretrained(AV)
    av_model = EmotionModel.from_pretrained(AV).to(dev).eval()
except Exception as e:  # emotion is a nice-to-have; never block the other scores
    print("emotion model unavailable:", e)


@torch.no_grad()
def av(path):
    x = av_proc(load16(path).numpy(), sampling_rate=16000, return_tensors="pt").input_values.to(dev)
    adv = av_model(x)[0].cpu().numpy()
    return float(adv[0]), float(adv[2])


# ---- score --------------------------------------------------------------------------------
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


out = {"asr_model": a.asr, "items": {}, "sources": {}}
print(f"scoring {len(m['items'])} takes: voice similarity" + (", re-transcribed with " + a.asr if ctc is not None else "")
      + (", emotion" if av_model is not None else ""), flush=True)
bar = Progress("scored", len(m["items"]))
for it in m["items"]:
    r = {}
    try:
        info = sf.info(it["wav"])
        r["dur_s"] = round(info.duration, 2)
        r["dur"] = round(info.duration / it["slot_s"], 2) if it.get("slot_s") else None
        r["sim"] = round(float(xvec(it["wav"]) @ centroids[it["speaker"]]), 3)
        if ctc is not None:
            hyp = transcribe(it["wav"])
            r["asr"] = hyp
            r["cer"] = round(cer(it["text"], hyp), 3)
        if av_model is not None and it.get("source_wav"):
            src = out["sources"].setdefault(it["source_wav"], av(it["source_wav"]))
            o = av(it["wav"])
            r["av"] = [round(o[0], 3), round(o[1], 3)]
            r["av_src"] = [round(src[0], 3), round(src[1], 3)]
            r["av_dist"] = round(float(np.hypot(o[0] - src[0], o[1] - src[1])), 3)
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"
    out["items"][it["key"]] = r
    if "error" in r:
        print(f"take {it['key']}: {r['error'][:200]}", flush=True)
    bar.step("error" not in r)

# Reference points: how similar is a real held-out clip to its own speaker's centroid?
out["real_sim"] = {spk: round(float(np.mean([float(xvec(w) @ centroids[spk]) for w in wavs])), 3)
                   for spk, wavs in m["speakers"].items()}
with open(a.out, "w", encoding="utf-8") as fh:  # closed (flushed) before os._exit below
    json.dump(out, fh, ensure_ascii=False, indent=1)
# Exit without interpreter teardown: on Windows the Intel XPU runtime can hang for
# minutes while shutting down, after all the work is saved.
import sys as _sys
_sys.stdout.flush()
_sys.stderr.flush()
os._exit(0)
