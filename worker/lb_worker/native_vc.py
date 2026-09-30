"""Native speech, then the character's voice: how a line is voiced when its language has
native voices here (decision 46; the owner's choice by ear on the camille test,
spikes/voice_paths, 2026-09-30).

1. OmniVoice (the language's fine-tune when there is one) says the line, prompted by a
   native speaker of the character's gender, so rhythm, pauses and pronunciation are
   the target language's own. Cloning straight from the English bank carried the
   bank's pause rate into the Amharic (a pause every ~8 words, most where the Amharic
   has no punctuation).
2. Seed-VC v1 (Whisper-small model, timbre only) turns that speech into the character's
   voice from its bank; the words and timing of step 1 stay.

Languages without native voices here keep direct cloning (``has_native``).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Native voices per language: human recordings from Addis AI's public Amharic TTS benchmark
# (huggingface.co/datasets/addisai/amharic-tts-benchmark), level-normalised before use.
# Chosen 2026-09-30: few or no pauses, 6-11 s; the female one is the voice of the approved test.
BENCH = "addisai/amharic-tts-benchmark"
NATIVE: dict[str, dict] = {
    "am": {
        "model": "african-low-resource/omnivoice-amharic",
        "female": {"file": "audio/human-reference/am-007.wav", "source": "FLEURS (google/fleurs), CC BY 4.0",
                   "text": "አዲስ ነገር ሲመጣ የቁልፍ ሰሌዳ ምን እንደሚሆን አንደ ሰው መገረም ብቻ ነው የሚችለው"},
        "male": {"file": "audio/human-reference/am-074.wav", "source": "Horn-ASR (LesanAI), CC BY-SA 4.0",
                 "text": "ኤልያስ ሃሰን እባላለሁ። ይሄ የለበስኩት የሶማሌ ባህል የጎልማሳ ወይም የትልቅ ሰው ልብስ የለበስኩት።"},
    },
}
SEEDVC_REPO = "https://github.com/Plachtaa/seed-vc"
SEEDVC_COMMIT = "51383efd921027683c89e5348211d93ff12ac2a8"  # the code of the approved test
FEMALE_HZ = 165  # median pitch at or above: a female native voice


def has_native(lang: str) -> bool:
    return lang in NATIVE


def path_for(lang: str, want: str | None) -> str:
    """How a language is voiced: "native_vc" (the default) where native voices exist,
    else "clone" (OmniVoice straight from the character's bank). ``want`` = "clone"
    forces cloning everywhere."""
    return "native_vc" if (want or "native_vc") == "native_vc" and has_native(lang) else "clone"


def fix_punct(text: str, lang: str) -> str:
    """Ethiopic punctuation for Ethiopic-script languages (the voice model phrases by it):
    English commas and semicolons become ፣ and ፤, a finished sentence ends with ።."""
    if lang not in ("am", "ti"):
        return text
    t = re.sub(r"\s*,\s*", "፣ ", text.strip())
    t = re.sub(r"\s*;\s*", "፤ ", t)
    if t.endswith(("...", "…")):  # a trailing-off sentence stays one
        return t
    t = re.sub(r"\.$", "።", t).strip()
    if t and t[-1] not in "።?!፧":
        t += "።"
    return t


def gender_of(wav: str | Path) -> str:
    """female/male from the median pitch of (up to 20 s of) a voice."""
    import librosa
    import numpy as np

    y, _ = librosa.load(str(wav), sr=16000, mono=True, duration=20)
    f0, voiced, _ = librosa.pyin(y, fmin=60, fmax=400, sr=16000)
    f0 = f0[voiced & ~np.isnan(f0)]
    return "female" if len(f0) and float(np.median(f0)) >= FEMALE_HZ else "male"


def voice_ref(lang: str, gender: str, cache: Path) -> tuple[str, str]:
    """The native voice for a language and gender, level-normalised (FLEURS' clip is
    recorded ~30 dB quieter than speech usually is, and OmniVoice copies the level):
    (wav path, its transcript)."""
    import numpy as np
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    v = NATIVE[lang][gender]
    out = cache / f"native_{lang}_{gender}.wav"
    if not out.exists():
        x, sr = sf.read(hf_hub_download(BENCH, v["file"], repo_type="dataset"), dtype="float32", always_2d=True)
        x = x.mean(1)
        x *= 10 ** (-20 / 20) / (np.sqrt((x ** 2).mean()) + 1e-9)  # -20 dBFS RMS
        x /= max(1.0, float(np.abs(x).max()) / 0.95)  # no clipping
        cache.mkdir(parents=True, exist_ok=True)
        sf.write(out, x, sr)
    return str(out), v["text"]


def seedvc_checkout(where: Path, cache: Path, pip, log) -> Path:
    """Seed-VC at the pinned commit, with the few packages its inference needs; its
    model downloads go to ``cache`` (Drive on Colab), so a new session does not
    download them again."""
    d = where / "seed-vc"
    ready = d / ".lb_ready"
    if ready.exists():
        return d
    import shutil

    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for cmd in (["git", "init", "-q"], ["git", "fetch", "-q", "--depth", "1", SEEDVC_REPO, SEEDVC_COMMIT],
                ["git", "checkout", "-q", "FETCH_HEAD"]):
        if subprocess.run(cmd, cwd=d).returncode:
            raise RuntimeError(f"getting Seed-VC failed at: {' '.join(cmd)}")
    # dac is only needed for one class; its dependencies (descript-audiotools, protobuf<3.20)
    # would break the session's other packages, and svc_batch.py never imports them
    if not (pip("munch", "einops") and pip("--no-deps", "descript-audio-codec")):
        raise RuntimeError("pip install of Seed-VC's packages failed")
    # the vendored BigVGAN wants two arguments current huggingface_hub no longer passes
    for f in d.rglob("bigvgan.py"):
        s = f.read_text(encoding="utf-8")
        s2 = re.sub(r"(\bproxies\s*:\s*[^,=)]+?)(\s*,)", r"\1 = None\2", s)
        s2 = re.sub(r"(\bresume_download\s*:\s*[^,=)]+?)(\s*,)", r"\1 = False\2", s2)
        f.write_text(s2, encoding="utf-8")
    ck = d / "checkpoints"
    shutil.rmtree(ck, ignore_errors=True)
    try:
        ck.symlink_to(cache, target_is_directory=True)
    except OSError:  # no symlinks here: download into the checkout
        ck.mkdir()
    ready.write_text(SEEDVC_COMMIT)
    log(f"Seed-VC ready ({SEEDVC_COMMIT[:7]})")
    return d


def convert_cmd(tts_dir: Path, seedvc: Path, manifest: Path, out: Path, steps: int = 25) -> list:
    return [sys.executable, tts_dir / "svc_batch.py", "--seedvc", seedvc, "--model", "whisper",
            "--manifest", manifest, "--out", out, "--steps", str(steps)]
