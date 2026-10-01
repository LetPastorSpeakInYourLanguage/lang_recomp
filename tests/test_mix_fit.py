import numpy as np

from app.mix import DEFAULTS, GAP_S, LEAD_S, fit, srt_time, speech_db


def L(i, s, e, d):
    return {"id": i, "start": s, "end": e, "dur": d}


def test_short_take_starts_at_the_original_onset():
    (p,) = fit([L(1, 2.0, 4.0, 1.5)], 10, DEFAULTS)
    assert p["start"] == 2.0 and p["factor"] == 1.0 and p["status"] == "fits"


def test_long_take_borrows_the_pause_after_it():
    a, b = fit([L(1, 0.0, 2.0, 3.0), L(2, 5.0, 6.0, 1.0)], 10, DEFAULTS)
    assert a["status"] == "borrowed" and a["start"] == 0.0 and a["end"] == 3.0
    assert b["start"] == 5.0


def test_long_take_may_start_a_little_early():
    # Window after onset is too short, but starting up to LEAD_S early makes it fit.
    (a, b) = fit([L(1, 1.0, 2.0, 2.2), L(2, 3.1, 4.0, 0.5)], 10, DEFAULTS)
    assert a["status"] == "borrowed" and a["factor"] == 1.0
    assert a["start"] >= 1.0 - LEAD_S - 1e-9 and a["end"] <= 3.1 - GAP_S + 1e-9


def test_stretch_levels():
    def one(d):
        return fit([L(1, 1.0, 2.0, d), L(2, 3.0, 4.0, 0.5)], 10, DEFAULTS)[0]
    room = (3.0 - GAP_S) - (1.0 - LEAD_S)
    assert one(room * 1.10)["status"] == "stretched"
    assert one(room * 1.20)["status"] == "squeezed"
    over = one(room * 1.6)
    assert over["status"] == "overflow" and over["factor"] == DEFAULTS["hard_stretch"] and over["overlap_s"] > 0


def test_a_line_starts_early_only_after_the_previous_take_has_ended():
    ps = fit([L(1, 0.0, 1.0, 1.0), L(2, 1.2, 2.0, 1.2), L(3, 2.2, 3.0, 0.5)], 10, DEFAULTS)
    assert ps[1]["start"] >= ps[0]["end"] + GAP_S - 1e-9


def test_a_take_too_long_plays_under_the_next_line_instead_of_delaying_it():
    ps = fit([L(1, 0.0, 1.0, 1.9), L(2, 1.2, 2.0, 0.5)], 10, DEFAULTS)
    assert ps[0]["status"] == "overflow" and ps[0]["end"] > 1.2
    assert ps[1]["start"] == 1.2  # its own onset, under the end of the first take


def test_the_dub_never_drifts_behind_the_picture():
    # every take half as long again as its line, back to back: before, each one pushed the rest later
    lines = [L(i, 2.0 * i, 2.0 * i + 1.8, 2.7) for i in range(30)]
    ps = fit(lines, 70, DEFAULTS)
    assert all(pl["start"] <= ln["start"] + 1e-9 for pl, ln in zip(ps, lines))
    assert ps[-1]["end"] < lines[-1]["end"] + 1.5


def test_speech_level_ignores_pauses():
    tone = 0.1 * np.sin(np.linspace(0, 2000, 48000)).astype(np.float32)
    with_pause = np.concatenate([tone, np.zeros(48000, np.float32)])
    assert abs(speech_db(tone) - speech_db(with_pause)) < 1.5


def test_srt_time():
    assert srt_time(3723.456) == "01:02:03,456"
