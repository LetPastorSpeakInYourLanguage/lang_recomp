"""Download the translation-loop models ahead of time (resumable; skips what is there).

    python scripts/fetch_models.py [--cache D:/LangBridgeLocal/cache/hf] [name ...]

Names (default: all): gemma4-e4b-ov, gemma3-4b-npu-ov, translategemma-4b-gguf, nllb-1.3b,
africomet-qe, labse. Uses the Hugging Face login of this machine (HF_TOKEN or `hf auth login`).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MODELS = {
    # instruction model (rephrase / judge / revise) on an Intel GPU, OpenVINO int4
    "gemma4-e4b-ov": ("OpenVINO/gemma-4-E4B-it-int4-ov", None),
    # the same role on an Intel NPU (channel-wise int4 is what the NPU runs)
    "gemma3-4b-npu-ov": ("OpenVINO/gemma-3-4b-it-int4-cw-ov", None),
    # translator; GGUF runs in llama.cpp on any GPU (Colab/Kaggle CUDA, Vulkan here)
    "translategemma-4b-gguf": ("mradermacher/translategemma-4b-it-GGUF", ["*.Q4_K_M.gguf", "README.md"]),
    # translator covering Amharic, Oromo, Tigrinya, Somali …
    "nllb-1.3b": ("facebook/nllb-200-distilled-1.3B", ["*.json", "*.model", "*.safetensors"]),
    # reference-free quality estimate for African languages
    "africomet-qe": ("masakhane/africomet-qe-stl", None),
    # sentence embeddings for back-translation similarity
    "labse": ("sentence-transformers/LaBSE", ["*.json", "*.txt", "model.safetensors", "1_Pooling/*", "2_Dense/*",
                                              "sentence_bert_config.json", "modules.json"]),
}


def main() -> None:
    args = sys.argv[1:]
    cache = Path(args[args.index("--cache") + 1]) if "--cache" in args else Path("D:/LangBridgeLocal/cache/hf")
    names = [a for a in args if a in MODELS] or list(MODELS)
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    from huggingface_hub import snapshot_download

    for name in names:
        repo, patterns = MODELS[name]
        t = time.time()
        print(f"{name}: {repo} …", flush=True)
        for attempt in range(5):
            try:
                path = snapshot_download(repo, allow_patterns=patterns)
                size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 2**30
                print(f"{name}: ready ({size:.1f} GB, {time.time() - t:.0f} s) at {path}", flush=True)
                break
            except Exception as e:  # gated, network: say so and go on with the others
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                if "gated" in msg.lower() or "401" in msg or "403" in msg:
                    print(f"{name}: needs access on huggingface.co/{repo} (accept its terms): {msg}", flush=True)
                    break
                print(f"{name}: attempt {attempt + 1} failed: {msg}; retrying", flush=True)
                time.sleep(15 * (attempt + 1))


if __name__ == "__main__":
    main()
