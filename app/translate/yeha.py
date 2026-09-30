"""YehaTranslate (Hasab AI): TranslateGemma-4B fine-tuned for English <-> Amharic,
Afaan Oromo and Tigrinya.

It runs on the machine's GPU, so it is meant for the notebook (TRANSLATOR = "yeha");
it never downloads anything on a machine without an NVIDIA GPU. The model is gated:
accept its terms once on https://huggingface.co/hasab-ai/YehaTranslate with the
account whose HF_TOKEN the notebook uses. Licence CC BY-NC 4.0 (non-commercial).

The model takes exactly one text per prompt, so every line is translated on its own
(no neighbouring lines as context, unlike the Google batches); lines are batched only
for GPU speed. A line it returns empty, or in the wrong script, is sent to the
fallback translator (Google) instead, and counted.
"""
from __future__ import annotations

from .. import langs
from .length import detect_script

MODEL = "hasab-ai/YehaTranslate"
LANGS = {"en", "am", "om", "ti"}

_loaded: dict[str, tuple] = {}  # model id -> (processor, model), loaded once per process


def supports(src: str, tgt: str) -> bool:
    """English to or from Amharic, Oromo or Tigrinya."""
    return src != tgt and {src, tgt} <= LANGS and "en" in (src, tgt)


def free() -> None:
    """Drop the loaded model and give its GPU memory back (before voicing)."""
    if not _loaded:
        return
    _loaded.clear()
    import gc

    import torch

    gc.collect()
    torch.cuda.empty_cache()


def _load(model_id: str):
    if model_id in _loaded:
        return _loaded[model_id]
    try:
        import torch
    except ImportError:
        torch = None
    if torch is None or not torch.cuda.is_available():
        raise RuntimeError("YehaTranslate needs an NVIDIA GPU: translate in the notebook "
                           "(TRANSLATOR = yeha), or use Google here")
    from transformers import AutoModelForImageTextToText, AutoProcessor

    # T4s (Colab, Kaggle) have no native bfloat16: half precision there.
    dtype = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
    proc = AutoProcessor.from_pretrained(model_id, use_fast=True)
    proc.tokenizer.padding_side = "left"  # batched generation continues every row at its end
    model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=dtype, device_map="auto").eval()
    _loaded[model_id] = (proc, model)
    return proc, model


class YehaTranslator:
    def __init__(self, src: str, tgt: str, fallback=None, batch: int = 8, model: str = MODEL):
        if not supports(src, tgt):
            raise ValueError(f"YehaTranslate does not translate {src} -> {tgt}")
        self.src, self.tgt, self.fallback, self.batch, self.model = src, tgt, fallback, batch, model
        self.fell_back = 0

    def translate(self, units: list[dict]) -> dict[int, str]:
        """units: [{'id': int, 'text': str}, ...] -> {id: translation}"""
        out: dict[int, str] = {}
        todo = sorted((u for u in units if u["text"].strip()), key=lambda u: len(u["text"]))  # similar lengths pad less
        for i in range(0, len(todo), self.batch):
            part = todo[i:i + self.batch]
            for u, text in zip(part, self._generate([u["text"] for u in part])):
                if self._plausible(text):
                    out[u["id"]] = text
        missing = [u for u in units if u["id"] not in out]
        if missing and self.fallback is not None:
            self.fell_back += len(missing)
            out |= self.fallback.translate(missing)
        return out

    def _plausible(self, text: str) -> bool:
        """Non-empty and in the target language's script (a model that overflows in
        half precision returns nothing, or repeats the source)."""
        want = langs.script(self.tgt)
        return bool(text.strip()) and (want is None or detect_script(text) == want)

    def _generate(self, texts: list[str]) -> list[str]:
        try:
            return self._run(texts)
        except Exception:  # one bad line (or a processor without batches) must not sink the rest
            if len(texts) == 1:
                return [""]
            return [self._generate([t])[0] for t in texts]

    def _run(self, texts: list[str]) -> list[str]:
        import torch

        proc, model = _load(self.model)
        msgs = [[{"role": "user", "content": [{"type": "text", "source_lang_code": self.src,
                                                "target_lang_code": self.tgt, "text": t.strip()}]}]
                for t in texts]
        inputs = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                          return_tensors="pt", padding=True).to(model.device)
        n_in = inputs["input_ids"].shape[1]
        with torch.inference_mode():
            gen = model.generate(**inputs, do_sample=False,
                                 max_new_tokens=min(512, 64 + 4 * max(len(t) for t in texts)))
        return [proc.decode(row[n_in:], skip_special_tokens=True).strip() for row in gen]
