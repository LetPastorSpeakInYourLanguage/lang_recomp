import numpy as np
import pytest
from scipy.io import wavfile

from app import fingerprint as fp

SR = 22050


def chords(seed: int, seconds: float) -> np.ndarray:
    """Music-like audio: a new random three-note chord every 0.4 s."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(int(seconds / 0.4)):
        t = np.arange(int(0.4 * SR)) / SR
        notes = 220 * 2 ** (rng.integers(0, 24, 3) / 12)
        x = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) for f in notes)
        out.append(x * np.hanning(len(t)) ** 0.2)
    return np.concatenate(out).astype(np.float32)


@pytest.fixture(scope="module")
def prints(tmp_path_factory):
    d = tmp_path_factory.mktemp("fp")
    intro = chords(1, 15)
    rng = np.random.default_rng(9)
    tracks = {
        "ep1": np.concatenate([chords(2, 20), intro, chords(3, 30)]),
        # the same intro, quieter and with noise, at another place
        "ep2": np.concatenate([chords(4, 5), 0.8 * intro + 0.05 * rng.standard_normal(len(intro)), chords(5, 40)]),
        "other": chords(6, 60),
    }
    out = {}
    for name, x in tracks.items():
        wavfile.write(d / f"{name}.wav", SR, (x / np.abs(x).max() * 20000).astype(np.int16))
        out[name] = fp.compute(d / f"{name}.wav")
    return out


def test_about_eight_frames_a_second(prints):
    # items start every FRAME_S and each describes ~2.6 s, so the last ~21 are missing
    assert 56 < len(prints["other"]) * fp.FRAME_S < 59


def test_a_known_part_is_found_where_it_occurs(prints):
    a, part = fp.part_frames(prints["ep1"], 20.0, 35.0)
    b = a + len(part)
    hits = fp.find_part(part, prints["ep2"])
    assert hits and abs(fp.to_seconds(hits[0][0]) - 4.8) <= 2 * fp.FRAME_S  # 12 chords of 0.4 s precede it
    assert fp.find_part(part, prints["other"]) == []
    # searching its own source, skipping its own place, finds nothing else
    assert fp.find_part(part, prints["ep1"], skip=(a, b)) == []


def test_shared_runs_discover_the_intro_without_being_told(prints):
    runs = fp.shared_runs(prints["ep1"], prints["ep2"], min_s=8)
    assert runs, "no shared run found"
    r = runs[0]
    assert abs(r["a_start"] - 20) < 0.3 and abs(r["b_start"] - 4.8) < 0.3
    assert abs(r["a_end"] - 35) < 0.5 and abs(r["b_end"] - 19.8) < 0.5
    assert fp.shared_runs(prints["ep1"], prints["other"], min_s=8) == []


def test_parts_too_short_to_search_are_refused(prints):
    with pytest.raises(ValueError):
        fp.part_frames(prints["ep1"], 20.0, 22.5)


def test_runs_bridge_short_gaps():
    ok = np.array([1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1], dtype=bool)
    assert fp._runs(ok, gap=3) == [(0, 7), (14, 15)]
