"""Certification benches (docs/SCALE_PLAN.md, Phase A): measure before we build.

    gpu       E1: speed and GPU use per stage, per setting (separation, Whisper, OmniVoice)
    identity  E2: is "the same video" recognised across copies, formats, trims and intros

Run from notebooks/bench_gpu_identity.ipynb; results land in OUT/bench/*.json and a printed
summary to paste back.
"""
