"""Shorter English for lines too long to fit (worker/lb_worker/shorten.py), with the model,
the embedder and Google stood in for."""
import re
import sys
import time
from pathlib import Path

import pytest

from app import db, project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import shorten  # noqa: E402

LONG = "ሰላም " * 10  # 30 syllables: 5 s at 6/s, in a ~1 s window
LINES = [  # (start, end, English, translation, provenance, locked, mode)
    (0.0, 1.0, "Hello and welcome to the programme.", LONG, "machine", 0, None),
    (1.1, 2.0, "I am Neil.", "ኒል", "machine", 0, None),
    (2.1, 3.0, "This one is locked.", LONG, "machine", 1, None),
    (3.1, 4.0, "Oh right, yes.", LONG, "machine", 0, "keep"),
    (4.1, 5.0, "A person wrote this one.", LONG, "human", 0, None),
    (5.1, 6.0, "And that is all for today, goodbye.", LONG, "machine", 0, None),
]


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    db.run("INSERT INTO projects (id,name,created,src_lang,tgt_lang,duration,meta) VALUES ('p','p',?,'en','am',6.5,?)",
           time.time(), '{"targets": ["ti"]}')
    for i, (a, b, en, tr, prov, locked, mode) in enumerate(LINES, 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text,mode) VALUES (?,?,?,?,?,?,?)",
               "p", i, "SPEAKER_00", a, b, en, mode)
        project.set_translation("p", i, "am", tr, locked=bool(locked), provenance=prov)
    yield tmp_path
    db._local.c = None


class Server:
    def __init__(self, fail=False, skip=()):
        self.prompts, self.starts, self.tokens, self.fail, self.skip = [], 0, 0, fail, set(skip)

    def __enter__(self):
        self.starts += 1
        if self.fail:
            raise RuntimeError("the model server stopped at start: out of memory")
        return self

    def __exit__(self, *a):
        pass

    def map(self, fn, items):
        return [fn(x) for x in items]

    def chat(self, messages, schema=None, max_tokens=0, full=False):
        user = messages[-1]["content"]
        self.prompts.append(user)
        self.tokens += 10
        ids = [int(i) for i in re.findall(r"\[(\d+)\*\]", user)]
        if len(self.prompts) == 1:  # the first answer leaves out some lines (cut short)
            ids = [i for i in ids if i not in self.skip]
        text = "Sure:\n" + "".join(f"{i}a: Short.\n**{i}b:** Tiny.\n" for i in ids)
        return {"text": text, "finish": "stop"}


class Google:
    calls: list = []

    def __init__(self, src, lang):
        self.lang = lang

    def translate(self, items):
        Google.calls.append((self.lang, [x["text"] for x in items]))
        return {x["id"]: "ሰላም" if x["text"] == "Short." else "ሰ" for x in items}


def sims(pairs):
    return [0.9 if short == "Short." else 0.5 for _, short in pairs]


def go(server, langs=("am",), sim=sims, raw_log=None):
    Google.calls = []
    return shorten.run(["p"], lambda pid: list(langs), lambda pid, lang: 6.0, Path("w"), Path("c"),
                       log=lambda *a: None, server=server, similarity=sim, translator=Google, raw_log=raw_log)


def test_only_lines_that_cannot_fit_are_shortened_and_people_are_never_overruled(fresh):
    srv = Server()
    rep = go(srv)
    marked = {int(i) for p in srv.prompts for i in re.findall(r"\[(\d+)\*\]", p)}
    assert marked == {1, 6}  # the first and the last line; not locked, kept or person-written ones
    assert "I am Neil." in srv.prompts[0]  # neighbours come along as context
    s = {x["id"]: x for x in project.sentences("p", "am")}
    assert s[1]["tr"] == "ሰላም" and s[1]["tr_provenance"] == "machine"
    assert [o["kind"] for o in s[1]["options"]] == ["google", "short_a", "short_b"]
    assert s[1]["options"][0]["text"] == LONG and s[1]["options"][1]["sim"] == 0.9
    for i in (3, 4, 5):
        assert s[i]["tr"] == LONG and s[i]["options"] == []
    assert rep["tight"] == 2 and rep["fits"] == 2 and rep["tokens"] == 10


def test_a_version_that_lost_the_meaning_is_kept_only_as_an_option(fresh):
    rep = go(Server(), sim=lambda pairs: [0.5] * len(pairs))
    s = project.sentences("p", "am")[0]
    assert s["tr"] == LONG and len(s["options"]) == 3 and rep["too_long"] == 2


def test_english_is_shortened_once_for_every_language(fresh):
    for i in (1, 6):
        project.set_translation("p", i, "ti", LONG, provenance="machine")
    srv = Server()
    rep = go(srv, langs=("am", "ti"))
    assert len(srv.prompts) == 1 and rep["tight"] == 4 and rep["fits"] == 4
    assert {lang for lang, _ in Google.calls} == {"am", "ti"}
    assert project.sentences("p", "ti")[0]["tr"] == "ሰላም"


def test_a_second_run_skips_lines_already_done(fresh):
    go(Server())  # both now fit: nothing left to do
    srv = Server()
    assert go(srv)["tight"] == 0 and srv.starts == 0
    low = lambda pairs: [0.5] * len(pairs)  # noqa: E731
    for i in (1, 6):
        project.set_translation("p", i, "am", LONG, provenance="machine")
    go(Server(), sim=low)  # still too long, versions stored: a restarted run does not ask again
    srv = Server()
    rep = go(srv, sim=low)
    assert srv.starts == 0 and rep["done_before"] == 2


def test_if_the_model_cannot_run_google_stays(fresh):
    rep = go(Server(fail=True))
    assert "out of memory" in rep["error"]
    assert project.sentences("p", "am")[0]["tr"] == LONG and project.options("p", "am") == {}


def test_nothing_starts_when_every_line_fits(fresh):
    for i in (1, 6):
        project.set_translation("p", i, "am", "ሰላም", provenance="machine")
    srv = Server()
    rep = go(srv)
    assert srv.starts == 0 and rep["tight"] == 0


def test_the_prompt_marks_lines_with_their_word_limits():
    text = shorten.prompt("Hope", [{"id": 1, "text": "Hi.", "speaker": "A"}, {"id": 2, "text": "Long line here."}], {2: (5, 3)})
    assert text.startswith("Chapter: Hope") and "[1] (A) Hi." in text
    assert "[2*] Long line here.   <- rewrite: a at most 5 words, b at most 3 words" in text


def test_lines_the_model_left_out_are_asked_again_and_every_answer_is_kept(fresh):
    srv = Server(skip={6})
    rep = go(srv, raw_log=fresh / "raw.jsonl")
    assert len(srv.prompts) == 2 and "[6*]" in srv.prompts[1] and "[1*]" not in srv.prompts[1]
    assert rep["fits"] == 2 and rep["failed"] == 0
    raw = [__import__("json").loads(x) for x in (fresh / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["got"] for r in raw] == [1, 1] and raw[0]["finish"] == "stop"


def test_answers_are_read_from_plain_lines_in_any_usual_form():
    got = shorten.parse_answer("Here you go:\n12a: Short one.\n**12b:** Tiny.\n[13*] a - Other\n13b) x\n"
                               "99a: not asked\n14a: <version a of line 14>", [12, 13, 14])
    assert got == {12: {"a": "Short one.", "b": "Tiny."}, 13: {"a": "Other", "b": "x"}}
