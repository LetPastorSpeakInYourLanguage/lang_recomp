from app.translate.ethiopic import am_syllables, budget, en_syllables
from app.translate.google_batch import GoogleBatchTranslator, _read_tags
from app.translate.sentences import sentences


def test_read_tags_is_lenient_about_mangled_brackets():
    got = _read_tags("[1] ሀ\n[[2]] ለ\n[3]] መ\n  [ 4 ] ሰ\nno tag")
    assert got == {1: "ሀ", 2: "ለ", 3: "መ", 4: "ሰ"}


def test_read_tags_drops_duplicated_ids():
    assert _read_tags("[[1]] a\n[[1]] b\n[[1]] c\n[[2]] d") == {2: "d"}


class FakeGoogle(GoogleBatchTranslator):
    """Echoes lines back tagged; drops the tag of ids in ``lose`` when batched."""

    def __init__(self, lose=(), **kw):
        super().__init__(pause_s=0, **kw)
        self.lose, self.requests = set(lose), []

    def raw(self, text):
        self.requests.append(text)
        lines = text.splitlines()
        if len(lines) == 1 and not lines[0].startswith("[["):
            return "AM:" + lines[0]
        out = []
        for ln in lines:
            k, body = ln[2:].split("]]", 1)
            out.append(("" if int(k) in self.lose and len(lines) > 1 else f"[{k}]") + " AM:" + body.strip())
        return "\n".join(out)


def units(n):
    return [{"id": i, "text": f"sentence {i}."} for i in range(1, n + 1)]


def test_batch_translates_every_unit_once_with_context():
    t = FakeGoogle()
    res = t.translate(units(5))
    assert res == {i: f"AM:sentence {i}." for i in range(1, 6)}
    assert len(t.requests) == 1


def test_lost_tag_halves_then_falls_back_to_bare_sentence():
    t = FakeGoogle(lose={3})
    res = t.translate(units(6))
    assert res[3] == "AM:sentence 3."
    assert set(res) == set(range(1, 7))
    assert len(t.requests) > 1


def test_batches_respect_char_limit():
    t = FakeGoogle(max_chars=60, context=1)
    res = t.translate(units(10))
    assert set(res) == set(range(1, 11))
    assert all(len(r) <= 60 for r in t.requests)


def test_ethiopic_syllables_skip_punctuation():
    assert am_syllables("ሰላም። እንዴት ነህ፧") == 9  # ሰ ላ ም + እ ን ዴ ት + ነ ህ
    assert en_syllables("Can you tell me a bit about yourself") == 10


def test_budget_ratio():
    b = budget("ሰላም እንዴት ነህ", slot_s=1.0, rate=5.0)
    assert b["syllables"] == 9 and b["ratio"] == 1.8 and b["max_syllables"] == 5


def test_sentences_split_on_punctuation_speaker_and_gap():
    asr = {"segments": [{"speaker": "A", "words": [
        {"w": "Hello", "start": 0.0, "end": 0.4, "spk": "A"},
        {"w": "there.", "start": 0.5, "end": 0.9, "spk": "A"},
        {"w": "How", "start": 1.0, "end": 1.2, "spk": "A"},
        {"w": "are", "start": 1.3, "end": 1.4, "spk": "B"},
        {"w": "you", "start": 3.0, "end": 3.2, "spk": "B"},
    ]}]}
    s = sentences(asr)
    # "How" starts a sentence right at a speaker change, so it goes with B's words.
    assert [x["text"] for x in s] == ["Hello there.", "How are", "you"]
    assert s[0]["start"] == 0.0 and s[0]["end"] == 0.9 and s[0]["speaker"] == "A"


def _w(text, spk, t, d=0.2):
    return {"w": text, "start": t, "end": t + d, "spk": spk}


def test_stray_boundary_word_joins_the_sentence_it_starts():
    # "...have? I have one sister": diarization put "I" in the asker's turn.
    words = [_w("have?", "A", 0.0), _w("I", "A", 0.3, 0.1), _w("have", "B", 0.5), _w("one", "B", 0.8), _w("sister.", "B", 1.1)]
    s = sentences({"segments": [{"words": words}]})
    assert [(x["speaker"], x["text"]) for x in s] == [("A", "have?"), ("B", "I have one sister.")]


def test_one_word_reply_keeps_its_speaker():
    words = [_w("sister.", "B", 0.0), _w("Okay.", "A", 0.3), _w("And", "B", 0.6), _w("more.", "B", 0.9)]
    s = sentences({"segments": [{"words": words}]})
    assert [(x["speaker"], x["text"]) for x in s] == [("B", "sister."), ("A", "Okay."), ("B", "And more.")]


def test_long_words_are_never_moved():
    words = [_w("have?", "A", 0.0), _w("Absolutely", "A", 0.3, 0.7), _w("yes.", "B", 1.1)]
    s = sentences({"segments": [{"words": words}]})
    assert s[1]["speaker"] == "A"
