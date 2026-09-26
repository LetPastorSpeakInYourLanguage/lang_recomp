from app.interjections import DEFAULT_KEEP_WORDS, effective_mode, suggest_keep

W = set(DEFAULT_KEEP_WORDS)


def test_short_interjections_are_kept():
    for text in ("Wow.", "Ehm", "Yeah.", "Oh, nice.", "Okay.", "uh-huh", "Mhm."):
        assert suggest_keep(text, 0.8, W), text


def test_real_content_is_dubbed():
    for text in ("Yes.", "No.", "That's crazy.", "Very cool.", "I have one little sister."):
        assert not suggest_keep(text, 0.8, W), text


def test_long_or_wordy_lines_are_dubbed():
    assert not suggest_keep("Oh, nice.", 2.5, W)  # too long in time
    assert not suggest_keep("oh yeah okay wow", 1.0, W)  # more than 3 words


def test_explicit_choice_wins():
    assert effective_mode("dub", "Wow.", 0.5, W) == "dub"
    assert effective_mode("keep", "A whole sentence here.", 3.0, W) == "keep"
    assert effective_mode(None, "Wow.", 0.5, W) == "keep"
