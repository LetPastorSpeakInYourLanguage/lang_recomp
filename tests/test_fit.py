"""Will a translation fit its line's window, before anything is voiced (app/translate/fit.py)."""
import time

import pytest

from app import db, mix, project
from app.translate import fit


def L(s, e, tr="x"):
    return {"start": s, "end": e, "tr": tr}


def test_the_window_stops_at_the_neighbours_source_times():
    lines = [L(0.0, 1.0), L(1.1, 2.0), L(4.0, 5.0)]
    assert fit.window(lines, 1) == pytest.approx((1.0 + fit.GAP_S, 4.0 - fit.GAP_S))
    # the first line may start up to LEAD_S early, never before 0; the last runs to the clip's end
    assert fit.window(lines, 0) == pytest.approx((0.0, 1.1 - fit.GAP_S))
    assert fit.window([L(2.0, 3.0), L(6.0, 7.0)], 0)[0] == pytest.approx(2.0 - fit.LEAD_S)
    assert fit.window(lines, 2, total_s=9.0) == pytest.approx((4.0 - fit.LEAD_S, 9.0))
    assert fit.window(lines, 2)[1] == 5.0  # no clip length known: its own end


def test_tight_means_the_mixer_would_overflow_even_at_its_hardest_squeeze():
    # predicted lengths at the mixer's limits, for a line between two neighbours
    lines = [L(0.0, 1.0), L(1.5, 3.0), L(4.0, 5.0)]
    lo, hi = fit.window(lines, 1)
    for factor, tight, status in ((1.2, False, "squeezed"), (1.3, True, "overflow")):
        dur = (hi - lo) * factor
        assert fit.is_tight(dur / (hi - lo)) is tight
        placed = mix.fit([{"id": 1, "start": 0.0, "end": 1.0, "dur": 1.0},  # the previous take fills its slot
                          {"id": 2, "start": 1.5, "end": 3.0, "dur": dur},
                          {"id": 3, "start": 4.0, "end": 5.0, "dur": 0.5}], 10, mix.DEFAULTS)
        assert placed[1]["status"] == status


def test_the_mixer_keeps_its_limits():
    assert (mix.GAP_S, mix.LEAD_S) == (0.08, 0.3)
    assert (mix.DEFAULTS["max_stretch"], mix.DEFAULTS["hard_stretch"]) == (1.12, 1.25)


def test_need_uses_the_native_rate_until_takes_measure_one():
    assert fit.rate_for("am") == 6.0 and fit.rate_for("am", 5.2) == 5.2
    assert fit.rate_for("fr") == 5.0  # the script's default
    text = " ".join(["ሰላም"] * 4)  # 12 syllables: 2 s at 6/s
    assert fit.need(text, "am", 6.0, (0.0, 1.0)) == pytest.approx(2.0)
    assert fit.of_lines([L(0, 1, text), L(2, 3, "")], "am", 6.0)[1] is None


def test_word_caps_aim_inside_the_free_stretch_with_a_safer_second():
    a, b = fit.word_caps(20, 1.6)
    assert a == 13 and b == 11 and b < a
    assert fit.word_caps(4, 3.0) == (3, 2)  # never below a few words


def C(kind, n, sim):
    return {"kind": kind, "text": kind, "need": n, "sim": sim}


def test_choose_prefers_the_most_faithful_version_that_fits():
    pick, status = fit.choose([C("google", 1.5, 1.0), C("short_a", 1.05, 0.9), C("short_b", 0.9, 0.8)])
    assert pick["kind"] == "short_a" and status == "fits"


def test_choose_never_takes_a_version_that_lost_the_meaning():
    pick, status = fit.choose([C("google", 1.5, 1.0), C("short_a", 1.0, 0.6), C("short_b", 1.2, 0.8)])
    assert pick["kind"] == "short_b" and status == "closer"
    pick, status = fit.choose([C("google", 1.5, 1.0), C("short_a", 1.0, 0.5), C("short_b", 0.9, 0.4)])
    assert pick["kind"] == "google" and status == "too_long"


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    yield tmp_path
    db._local.c = None


def test_lines_carry_their_fit(fresh):
    db.run("INSERT INTO projects (id,name,created,tgt_lang,duration) VALUES ('p','p',?,'am',10)", time.time())
    for i, (a, b, t) in enumerate([(0.0, 1.0, "Hello."), (1.2, 2.0, "How are you?"), (6.0, 7.0, "Bye.")], 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES (?,?,?,?,?,?)", "p", i, "A", a, b, t)
    project.set_translation("p", 1, "am", "ሰላም ሰላም ሰላም ሰላም ሰላም", provenance="machine")  # 10 syllables in ~1.1 s
    project.set_translation("p", 3, "am", "ደህና ሁን", provenance="machine")
    s = {x["id"]: x for x in project.sentences("p", "am")}
    assert s[1]["fit"]["tight"] and s[1]["fit"]["need"] > 1.25
    assert s[2]["fit"] is None
    assert not s[3]["fit"]["tight"]
