# Certification results (Phase A of [SCALE_PLAN.md](SCALE_PLAN.md))

Numbers from the benches (`worker/lb_worker/bench/`, notebook `colab/bench_gpu_identity.ipynb`,
local `scripts/bench_local.py`). Each section ends with the decision it supports.

## E1 · GPU speed

### Intel Arc (Core Ultra 7 165H iGPU, 15.4 GB RAM shared), 2026-09-27

Excerpts: 2 × 6 Minute English (130 s of audio in all).

**Separation** (BS-RoFormer, overlap 2):

| Setting | Time | × real time | GPU busy | GPU memory | vs batch 1 |
|---|---|---|---|---|---|
| batch 1 | 275 s | 0.47 | 40 % | 5.6 GB | — |
| batch 4 | 268 s | 0.49 | 24–61 % | 5.6 GB | identical (−247 dB) |
| batch 8 | 261 s | 0.50 | 42 % | 5.7 GB | identical |
| batch 8 + autocast | 273 s | 0.48 | 77 % | 5.9 GB | −76 dB (inaudible) |
| batch 8 + fp16 | 259 s | 0.50 | 41 % | 5.9 GB | identical (fp16 not applied on XPU) |

The Arc is compute-bound: no setting is faster than ~0.5× real time. The GPU graph
saw-tooths because the separator does CPU work (window preparation, stitching) and host↔GPU
copies between GPU bursts; RAM (95 % used while the bench ran, since the iGPU's memory is
system RAM) is the local limit. → On this PC: batch 8, no half precision; separation is the
slow stage (~2 min per minute of audio). Parallel separators: to measure on the T4.

**Audio copy for Kaggle** (separation from Opus vs from the original, vocals SNR):
Opus 160 kb/s 30.5 / 31.3 dB · Opus 96 kb/s 25.5 / 25.9 dB. → 160 kb/s (listen to confirm).

**Whisper large-v3-turbo on the CPU** (int8): 1.0× real time at batch 8 and 16, identical
words. → On this PC Whisper is as slow as the audio; long libraries belong on a notebook GPU.

**OmniVoice** (Arc, 16 takes, 16 steps): _running_.

### Colab T4, 2026-09-27 (3 × 130 s excerpts of 6 Minute English, 390 s of audio)

**Separation** (BS-RoFormer, overlap 2):

| Setting | Time | × real time | GPU busy | GPU memory | vs batch 1 |
|---|---|---|---|---|---|
| batch 1 (run #1's setting) | 296 s | 1.32 | 92 % | 3.0 GB | — |
| batch 4 / 8 / 16 | 290–292 s | 1.34–1.35 | 97 % | 3.0 GB | identical (−248 dB) |
| batch 8 / 16 + autocast | 114 s | 3.4 | 92 % | 2.4 GB | −74.6 dB (inaudible) |
| **batch 16 + native fp16** | **109 s** | **3.57** | 92 % | 2.4 GB | **−74.6 dB (inaudible)** |

The T4 is already >90 % busy at batch 1 (Colab's "GPU RAM 2.5 / 15 GB" panel shows memory,
not load): batching cannot fill it more. Half precision makes each step cheaper on the T4's
tensor cores. → **Separation in native fp16 on CUDA** (now the default in
`load_separator`): 2.7× faster; run #1's 31 min of separation becomes ~11 min. Parallel
separators on one GPU: not pursued (GPU already busy; owner: keep it simple).

**Audio copy** (vocals SNR, separation from Opus vs original): Opus 160 kb/s 30.0 / 31.3 /
30.1 dB; 96 kb/s 23.9–25.7 dB. → Kaggle audio copies at **Opus 160 kb/s**.

**Whisper large-v3** (batched, 390 s): batch 8 16.2 s (24×), **16: 14.6 s (27×)**, 32: 14.8 s;
GPU 88 %, 5.4–7.3 GB, identical words. → keep batch 16; transcription is not a bottleneck.

**OmniVoice** (32 Amharic takes, 16 steps, one reused voice prompt; model load 58 s):
takes per call 1: 36.3 s (52.9 takes/min, GPU 98 %) · 4: 37.3 s · 8: 38.4 s · 16: 38.4 s.
→ **one take per call** (batching adds nothing: the GPU is already full). Run #1's 439
takes ≈ 8 min.

**Summary for a 6-minute video on a T4**: Whisper ~15 s, separation ~100 s (fp16),
~75 takes ≈ 1.5 min, plus alignment, speakers, scoring and mixing. Separation stays the
largest GPU stage; the GPU is busy (≥ 88 %) in every stage, so a T4's output is set by the
models, not by how we feed them.

### Pipeline run with these settings (Colab T4, 2026-09-27)

`colab/lang_bridge.ipynb` on the 6 Minute English playlist, 3 videos, 2 dubbed into Amharic,
end to end, **23 min** in all. Separation (fp16): a 6-min video in 112 s (run #1: ~305 s).
Voicing: 206 takes in 549 s (2.3 s per real line), progress every 30 s. Scoring: 175 s
(2 near-empty takes crashed the Amharic recogniser → now skipped). Mixing + export on the
CPU: 136–138 s per video (next thing to speed up).

### Kaggle 2 × T4

_Pending: the account needs phone verification for GPUs._

## E2 · Video identity (Colab, 2026-09-27)

Two 6 Minute English videos, each as: an exact copy, a second download at 360p, a 240p
re-encode, an MP3, a copy with the first 10 s cut, and one with 7 s of another episode in
front; matched against 5 other episodes. Chromaprint by Colab's own ffmpeg.

| Variant | Quick hash equal | Offset found (expected) | Mean differing bits (of 32) |
|---|---|---|---|
| exact copy | yes | 0 (0) | 0.0 |
| re-download 360p | no | 0 (0) | 0.0 |
| re-encode 240p | no | 0 (0) | 0.52–0.55 |
| MP3 | no | 0 (0) | 0.07–0.08 |
| first 10 s cut | no | +10.03 (+10) | 1.70–1.78 |
| 7 s intro added | no | −7.06 (−7) | 2.49–2.55 |
| any other episode (best) | — | — | ≥ 13.59 |

All five usual forms of a YouTube link gave the same `Youtube:<id>`.

→ Identity = link id, else quick hash (copies only), else fingerprint of a 60 s window with
**threshold 8 bits** (positives ≤ 2.6, negatives ≥ 13.6: a wide gap), offset applied to all
line times. A re-download never has the same bytes, so the fingerprint is the key for
link sources re-fetched by different members.

## E3–E6

_Pending._
