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

### Colab T4 / Kaggle 2 × T4

_Owner runs `colab/bench_gpu_identity.ipynb` (branch `exp/scale`) and pastes the summary._

## E2 · Video identity

_Pending (Colab/Kaggle notebook; local run after E1)._

## E3–E6

_Pending._
