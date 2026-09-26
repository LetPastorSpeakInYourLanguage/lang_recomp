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
    "nso": ("Sepedi", "nso", "latin"), "ro": ("Romanian", "ron", "latin"),
    "pcm": ("Nigerian Pidgin", "pcm", "latin"), "ne": ("Nepali", "nep", "devanagari"),
    "ve": ("Tshivenda", "ven", "latin"), "sn": ("Shona", "sna", "latin"),
    "tn": ("Setswana", "tsn", "latin"), "st": ("Sesotho", "sot", "latin"),
    "ts": ("Xitsonga", "tso", "latin"), "ny": ("Chichewa", "nya", "latin"),
    "pl": ("Polish", "pol", "latin"), "ta": ("Tamil", "tam", "tamil"), "te": ("Telugu", "tel", "telugu"),
    "ml": ("Malayalam", "mal", "malayalam"), "kn": ("Kannada", "kan", "kannada"),
}

# Names people give folders and files ("Italiano", "Español", "Mandarin", "Pidgin"…) → code.
_ALIASES = {"italiano": "it", "español": "es", "espanol": "es", "français": "fr", "francais": "fr",
            "deutsch": "de", "português": "pt", "portugues": "pt", "mandarin": "zh", "chinese": "zh",
            "pidgin": "pcm", "nigerian pidgin": "pcm", "venda": "ve", "tshivenda": "ve", "northern sotho": "nso",
            "setswana": "tn", "tswana": "tn", "sesotho": "st", "isizulu": "zu", "isixhosa": "xh", "kiswahili": "sw",
            "amharic": "am", "afaan oromoo": "om", "oromo": "om", "tigrinya": "ti", "farsi": "fa"}


def from_name(text: str) -> str | None:
    """A language code for a name as people write it (English or native), or None."""
    t = text.strip().lower()
    if t in _ALIASES:
        return _ALIASES[t]
    for code, (nm, _, _) in KNOWN.items():
        if t == nm.lower():
            return code
    return None


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
