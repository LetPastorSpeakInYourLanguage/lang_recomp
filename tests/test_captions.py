from app import captions

SRT = """1
00:00:00,500 --> 00:00:02,000
Hello and welcome.

2
00:00:02,400 --> 00:00:05,000
I'm Neil. <i>And I'm Georgie.</i>

3
00:00:09,000 --> 00:00:10,000
[Music]
"""

# YouTube automatic captions: each cue repeats the previous line, then adds timed words.
AUTO = """WEBVTT
Kind: captions
Language: en

00:00:00.160 --> 00:00:02.310 align:start position:0%

hello<00:00:00.960><c> and</c><00:00:01.200><c> welcome</c>

00:00:02.310 --> 00:00:02.320 align:start position:0%
hello and welcome


00:00:02.320 --> 00:00:04.990 align:start position:0%
hello and welcome
to<00:00:02.560><c> six</c><00:00:02.800><c> minute</c><00:00:03.100><c> english</c>
"""


def test_manual_subtitles_become_segments_with_spread_word_times():
    doc = captions.load(SRT, "en")
    assert [s["text"] for s in doc["segments"]] == ["Hello and welcome.", "I'm Neil.", "And I'm Georgie."]
    w = doc["segments"][0]["words"]
    assert w[0]["start"] == 0.5 and abs(w[-1]["end"] - 2.0) < 0.01 and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(w, w[1:]))
    assert doc["source"] == "captions"


def test_automatic_captions_keep_their_word_times_and_drop_repeats():
    cues = captions.parse(AUTO)
    assert len(cues) == 2  # the 10 ms repeat cue is gone
    doc = captions.to_doc(cues, "en", max_gap=0.8)
    words = [w for s in doc["segments"] for w in s["words"]]
    assert [w["w"] for w in words] == ["hello", "and", "welcome", "to", "six", "minute", "english"]
    assert (words[1]["start"], words[4]["start"]) == (0.96, 2.56)
    assert words[2]["end"] == 2.31  # until the next word
