"""Languages the app knows by name.

Any ISO 639-1/-3 code is accepted everywhere; this table only adds a display name,
the ISO 639-3 tag that video containers want for audio/subtitle tracks, the script
(for length estimation) and the name speech models expect ("Amharic", not "am").
"""
from __future__ import annotations

# code: (name, iso639-3, script)
KNOWN: dict[str, tuple[str, str, str]] = {
    "en": ("English", "eng", "latin"), "am": ("Amharic", "amh", "ethiopic"),
    "om": ("Oromo", "orm", "latin"), "ti": ("Tigrinya", "tir", "ethiopic"),
    "so": ("Somali", "som", "latin"), "sid": ("Sidamo", "sid", "latin"),
    "wal": ("Wolaytta", "wal", "latin"), "aa": ("Afar", "aar", "latin"),
    "sw": ("Swahili", "swa", "latin"), "yo": ("Yoruba", "yor", "latin"),
    "ha": ("Hausa", "hau", "latin"), "ig": ("Igbo", "ibo", "latin"),
    "zu": ("Zulu", "zul", "latin"), "xh": ("Xhosa", "xho", "latin"),
    "af": ("Afrikaans", "afr", "latin"), "rw": ("Kinyarwanda", "kin", "latin"),
    "lg": ("Luganda", "lug", "latin"), "ln": ("Lingala", "lin", "latin"),
    "wo": ("Wolof", "wol", "latin"), "ar": ("Arabic", "ara", "arabic"),
    "fr": ("French", "fra", "latin"), "es": ("Spanish", "spa", "latin"),
    "pt": ("Portuguese", "por", "latin"), "de": ("German", "deu", "latin"),
    "it": ("Italian", "ita", "latin"), "nl": ("Dutch", "nld", "latin"),
    "ru": ("Russian", "rus", "cyrillic"), "uk": ("Ukrainian", "ukr", "cyrillic"),
    "tr": ("Turkish", "tur", "latin"), "fa": ("Persian", "fas", "arabic"),
    "hi": ("Hindi", "hin", "devanagari"), "bn": ("Bengali", "ben", "bengali"),
    "ur": ("Urdu", "urd", "arabic"), "zh": ("Chinese", "zho", "cjk"),
    "ja": ("Japanese", "jpn", "cjk"), "ko": ("Korean", "kor", "hangul"),
    "id": ("Indonesian", "ind", "latin"), "vi": ("Vietnamese", "vie", "latin"),
    "tl": ("Tagalog", "tgl", "latin"), "he": ("Hebrew", "heb", "hebrew"),
}


def name(code: str) -> str:
    return KNOWN.get(code, (code,))[0]


def iso3(code: str) -> str:
    """Container language tag; 'und' (undetermined) for codes we cannot map."""
    if code in KNOWN:
        return KNOWN[code][1]
    return code if len(code) == 3 and code.isalpha() else "und"


def script(code: str) -> str | None:
    return KNOWN[code][2] if code in KNOWN else None


def catalogue() -> list[dict]:
    return [{"code": c, "name": n, "iso3": i, "script": s} for c, (n, i, s) in sorted(KNOWN.items(), key=lambda kv: kv[1][0])]
