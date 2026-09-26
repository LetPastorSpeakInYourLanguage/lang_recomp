"""Google Translate, batched for context and verified line by line.

Each request carries a block of target sentences plus a few neighbours on each
side as context. Every line is tagged ``[[id]]``; Google keeps the newlines but
mangles the brackets (``[[4]]`` can come back as ``[4]]``), so tags are read back
leniently and a batch counts only if every target id returns exactly once.
Otherwise the block is halved and retried, down to single sentences.

No key is needed. When an LLM engine is added it implements the same
``Translator.translate(units)`` shape.
"""
from __future__ import annotations

import re
import time
from typing import Protocol

import requests

MAX_CHARS = 4500
_TAG = re.compile(r"^\s*\[+\s*(\d+)\s*\]+\s*")

# Tried in order. The first is the Chrome-extension endpoint, which kept answering
# when the classic gtx endpoint started returning 429 for this network.
ENDPOINTS = [
    ("https://clients5.google.com/translate_a/t", {"client": "dict-chrome-ex"}, "dict"),
    ("https://translate.googleapis.com/translate_a/single", {"client": "gtx", "dt": "t"}, "gtx"),
]


class Translator(Protocol):
    def translate(self, units: list[dict]) -> dict[int, str]: ...


class GoogleBatchTranslator:
    def __init__(self, src: str = "en", tgt: str = "am", context: int = 2,
                 max_chars: int = MAX_CHARS, pause_s: float = 1.0, session=None):
        self.src, self.tgt, self.context = src, tgt, context
        self.max_chars, self.pause_s = max_chars, pause_s
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = "Mozilla/5.0"
        self.calls = 0

    # ---- transport ---------------------------------------------------------------------
    def raw(self, text: str) -> str:
        last = None
        for attempt in range(4):
            for url, extra, kind in ENDPOINTS:
                try:
                    r = self.http.post(url, params={"sl": self.src, "tl": self.tgt, **extra},
                                       data={"q": text}, timeout=30)
                    self.calls += 1
                    if r.status_code == 200:
                        return _parse(r.json(), kind)
                    last = f"{kind} HTTP {r.status_code}"
                except (requests.RequestException, ValueError) as e:
                    last = f"{kind} {type(e).__name__}"
            time.sleep(self.pause_s * 2 ** (attempt + 1))
        raise RuntimeError(f"translation failed: {last}")

    # ---- batching ----------------------------------------------------------------------
    def translate(self, units: list[dict]) -> dict[int, str]:
        """units: [{'id': int, 'text': str}, ...] in reading order -> {id: translation}"""
        out: dict[int, str] = {}
        i = 0
        while i < len(units):
            j = i
            size = 0
            while j < len(units) and size + len(units[j]["text"]) + 10 < self.max_chars * 0.8:
                size += len(units[j]["text"]) + 10
                j += 1
            j = max(j, i + 1)
            self._block(units, i, j, out)
            i = j
        return out

    def _block(self, units: list[dict], i: int, j: int, out: dict[int, str]) -> None:
        ctx = self.context
        while True:
            lo, hi = max(0, i - ctx), min(len(units), j + ctx)
            request = "\n".join(f"[[{u['id']}]] {_clean(u['text'])}" for u in units[lo:hi])
            if len(request) <= self.max_chars or (j - i == 1 and ctx == 0):
                break
            if j - i > 1:  # too big with its context: split the targets first
                mid = (i + j) // 2
                self._block(units, i, mid, out)
                self._block(units, mid, j, out)
                return
            ctx -= 1  # one huge sentence: shed context rather than fail
        want = {u["id"] for u in units[i:j]}
        got = _read_tags(self.raw(request))
        if self.pause_s:
            time.sleep(self.pause_s)
        if want <= got.keys():
            for k in want:
                out[k] = got[k]
            return
        if j - i > 1:
            mid = (i + j) // 2
            self._block(units, i, mid, out)
            self._block(units, mid, j, out)
            return
        # A single sentence whose tag still did not survive: translate it bare.
        out[units[i]["id"]] = _strip_invisible(self.raw(_clean(units[i]["text"])))


def _parse(data, kind: str) -> str:
    if kind == "dict":  # ["translated"] or [["translated", "en"]]
        first = data[0]
        return first if isinstance(first, str) else first[0]
    return "".join(part[0] for part in data[0] if part and part[0])


def _read_tags(text: str) -> dict[int, str]:
    got: dict[int, str] = {}
    dup: set[int] = set()
    for line in text.splitlines():
        m = _TAG.match(line)
        if not m:
            continue
        k = int(m.group(1))
        if k in got or k in dup:  # duplicated tag is ambiguous: force a retry of it
            dup.add(k)
            got.pop(k, None)
            continue
        got[k] = _strip_invisible(line[m.end():])
    return got


_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


def _strip_invisible(s: str) -> str:
    """Google sometimes returns zero-width spaces; TTS engines read them as pauses
    or garbage, and they break syllable counts."""
    return " ".join(s.translate(_INVISIBLE).split())


def _clean(s: str) -> str:
    return " ".join(s.split())
