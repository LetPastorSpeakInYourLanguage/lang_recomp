from app.project import carry_over, keep_reviewed


def test_reviewed_lines_are_never_replaced():
    # The person merged two lines into one reviewed line; the reload regroups them apart again.
    old = [{"id": 5, "start": 0.0, "end": 4.0, "reviewed": 1, "text": "merged"},
           {"id": 6, "start": 5.0, "end": 6.0, "reviewed": 0, "text": "loose"}]
    new = [{"id": 1, "start": 0.1, "end": 2.0, "text": "a"}, {"id": 2, "start": 2.0, "end": 4.0, "text": "b"},
           {"id": 3, "start": 5.1, "end": 6.0, "text": "c"}]
    locked, added = keep_reviewed(old, new)
    assert [o["id"] for o in locked] == [5]
    assert [s["text"] for s in added] == ["c"] and added[0]["id"] == 7  # fresh id, no collision


def row(i, s, e, text="x", am="", reviewed=0, speaker="A", chapter=0, locked=0):
    return {"id": i, "start": s, "end": e, "text": text, "am": am, "reviewed": reviewed, "speaker": speaker,
            "chapter_break": chapter, "am_locked": locked}


def test_shifted_lines_keep_translation_and_review():
    old = [row(1, 0.0, 2.0, "Hello there.", am="ሰላም", reviewed=1, speaker="B", chapter=1), row(2, 2.5, 4.0, am="ደህና")]
    new = [{"id": 1, "start": 0.2, "end": 2.1, "text": "Hello their.", "speaker": "A"},
           {"id": 2, "start": 2.7, "end": 4.1, "text": "x", "speaker": "A"}]
    kept = carry_over(old, new)
    assert kept == {1: 1, 2: 2}
    assert new[0]["am"] == "ሰላም" and new[0]["chapter_break"] == 1
    assert new[0]["text"] == "Hello there." and new[0]["speaker"] == "B"  # reviewed: the person's version wins
    assert new[1]["am"] == "ደህና" and new[1].get("reviewed") == 0


def test_unreviewed_line_takes_the_new_text_and_speaker():
    old = [row(1, 0.0, 2.0, "old words", am="x")]
    new = [{"id": 1, "start": 0.1, "end": 2.0, "text": "new words", "speaker": "C"}]
    carry_over(old, new)
    assert new[0]["text"] == "new words" and new[0]["speaker"] == "C" and new[0]["am"] == "x"


def test_lines_that_changed_shape_are_not_matched():
    old = [row(1, 0.0, 6.0, am="long")]
    new = [{"id": 1, "start": 0.0, "end": 2.0, "text": "a"}, {"id": 2, "start": 2.0, "end": 6.0, "text": "b"}]
    kept = carry_over(old, new)
    # The 4 s half overlaps 67% of the old span: it inherits; the 2 s half does not.
    assert kept == {1: 2} and "am" not in new[0]


def test_each_old_line_is_used_once():
    old = [row(1, 0.0, 2.0, am="one")]
    new = [{"id": 1, "start": 0.0, "end": 2.0, "text": "a"}, {"id": 2, "start": 0.1, "end": 2.0, "text": "b"}]
    assert carry_over(old, new) == {1: 1}
