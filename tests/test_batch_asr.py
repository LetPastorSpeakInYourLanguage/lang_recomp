import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import batch_asr as b  # noqa: E402


def test_speech_merges_into_windows_of_at_most_30_s():
    speech = [(0.5, 4.0), (5.0, 20.0), (21.0, 33.0), (40.0, 110.0)]
    w = b.merge_windows(speech, max_s=29.5)
    assert w[0] == (0.5, 20.0) and w[1] == (21.0, 33.0)
    assert all(e - s <= 29.5 + 1e-9 for s, e in w)
    assert w[-1][1] == 110.0 and len([x for x in w if x[0] >= 40.0]) == 3  # 70 s of speech in three windows


def test_videos_join_and_results_split_back_to_their_own_times():
    a = np.zeros(10 * b.SR, dtype=np.float32)
    c = np.zeros(4 * b.SR, dtype=np.float32)
    signal, clips, offsets = b.join({"a": a, "c": c}, {"a": [(1.0, 9.0)], "c": [(0.5, 3.5)]}, gap_s=1.0)
    assert len(signal) == (10 + 1 + 4 + 1) * b.SR
    assert offsets == {"a": 0.0, "c": 11.0} and clips[1] == {"start": 11.5, "end": 14.5}
    segs = [{"start": 1.2, "end": 3.0, "text": "one", "words": [{"w": "one", "start": 1.2, "end": 1.6}]},
            {"start": 11.6, "end": 13.0, "text": "two", "words": [{"w": "two", "start": 11.6, "end": 12.0}]}]
    out = b.split(segs, offsets)
    assert out["a"][0]["start"] == 1.2 and out["c"][0]["start"] == 0.6 and out["c"][0]["words"][0]["end"] == 1.0
