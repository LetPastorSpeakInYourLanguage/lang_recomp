"""Finding and vetting forced-alignment models on the Hugging Face Hub.

Any CTC model with a character vocabulary can align text in its language. The Hub
cannot be queried for that directly, so search casts a wide net (models tagged
with the language, plus a free-text search), marks the likely CTC families by tag,
and ``check`` settles it: the architecture must end in ``ForCTC`` and the
vocabulary must cover the characters of a sample in that language.
"""
from __future__ import annotations

import requests

HUB = "https://huggingface.co/api/models"
CTC_TAGS = {"wav2vec2", "wav2vec2-bert", "hubert", "wavlm", "data2vec-audio", "mms", "unispeech", "unispeech-sat", "sew"}
# A line of real text per language, used to test vocabulary coverage when the
# caller has none of their own. Extend freely.
SAMPLES = {
    "en": "So thank you so much for being here today",
    "am": "ሰላም እንዴት ነህ ዛሬ በጣም አመሰግናለሁ",
    "om": "Akkam jirta har'a baay'ee galatoomi",
    "ti": "ሰላም ከመይ ኣለኻ ሎሚ ብጣዕሚ የቐንየለይ",
}
NAMES = {"en": "english", "am": "amharic", "om": "oromo", "ti": "tigrinya", "so": "somali", "sw": "swahili"}


def search(language: str, q: str = "", limit: int = 25) -> list[dict]:
    seen: dict[str, dict] = {}
    queries = [{"filter": language, "pipeline_tag": "automatic-speech-recognition"}]
    if q or language in NAMES:
        queries.append({"search": q or NAMES[language], "pipeline_tag": "automatic-speech-recognition"})
    if q:
        queries[0]["search"] = q
    for params in queries:
        r = requests.get(HUB, params={**params, "sort": "downloads", "direction": -1, "limit": 60,
                                      "full": "false"}, timeout=20)
        r.raise_for_status()
        for m in r.json():
            tags = set(m.get("tags", []))
            seen.setdefault(m["id"], {
                "id": m["id"], "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                "ctc_likely": bool(tags & CTC_TAGS), "tagged_language": language in tags,
                "family": sorted(tags & CTC_TAGS),
            })
    rows = sorted(seen.values(), key=lambda m: (not m["ctc_likely"], not m["tagged_language"], -m["downloads"]))
    return rows[:limit]


def check(repo: str, language: str, sample: str | None = None) -> dict:
    """Can ``repo`` align ``language``? Reads only its metadata and vocabulary."""
    info = requests.get(f"{HUB}/{repo}", timeout=20)
    if info.status_code != 200:
        return {"ok": False, "reason": f"not found on the Hub ({info.status_code})"}
    meta = info.json()
    arch = (meta.get("config") or {}).get("architectures") or []
    files = {s["rfilename"] for s in meta.get("siblings", [])}
    out = {"repo": repo, "architectures": arch, "license": (meta.get("cardData") or {}).get("license"),
           "downloads": meta.get("downloads"), "gated": bool(meta.get("gated"))}
    if not any(a.endswith("ForCTC") for a in arch):
        return out | {"ok": False, "reason": f"architecture {arch or 'unknown'} is not CTC; alignment needs *ForCTC"}
    if "vocab.json" not in files:
        return out | {"ok": False, "reason": "no vocab.json: cannot map text to the model's characters"}
    vocab = requests.get(f"https://huggingface.co/{repo}/resolve/main/vocab.json", timeout=30).json()
    if vocab and isinstance(next(iter(vocab.values())), dict):  # multilingual: {lang: {char: id}}
        vocab = vocab.get(language) or vocab.get(_iso3(language)) or next(iter(vocab.values()))
    text = sample or SAMPLES.get(language, "")
    chars = [c for c in text if not c.isspace()]
    covered = [c for c in chars if c in vocab or c.lower() in vocab or c.upper() in vocab]
    coverage = len(covered) / len(chars) if chars else None
    single = sum(1 for k in vocab if len(k) == 1) / max(1, len(vocab))
    out |= {"vocab_size": len(vocab), "char_level": single > 0.8, "coverage": round(coverage, 3) if coverage is not None else None,
            "missing": sorted({c for c in chars if c not in covered})[:20]}
    if single <= 0.8:
        return out | {"ok": False, "reason": "vocabulary is not character-level (sub-word tokens cannot be force-aligned per character)"}
    if coverage is not None and coverage < 0.9:
        return out | {"ok": False, "reason": f"vocabulary covers only {coverage:.0%} of the sample text; wrong script or romanised model"}
    return out | {"ok": True, "reason": "CTC model with a character vocabulary covering the sample" if coverage is not None
                  else "CTC model with a character vocabulary (no sample text to test coverage)"}


def _iso3(code: str) -> str:
    return {"am": "amh", "en": "eng", "om": "orm", "ti": "tir", "so": "som", "sw": "swh"}.get(code, code)
