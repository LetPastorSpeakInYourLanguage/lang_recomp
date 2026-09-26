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


def row(i, s, e, text="x", reviewed=0, speaker="A", chapter=0):
    return {"id": i, "start": s, "end": e, "text": text, "reviewed": reviewed, "speaker": speaker,
            "chapter_break": chapter}


def test_shifted_lines_keep_their_review_and_map_ids():
    old = [row(1, 0.0, 2.0, "Hello there.", reviewed=1, speaker="B", chapter=1), row(2, 2.5, 4.0)]
    new = [{"id": 1, "start": 0.2, "end": 2.1, "text": "Hello their.", "speaker": "A"},
           {"id": 2, "start": 2.7, "end": 4.1, "text": "x", "speaker": "A"}]
    kept = carry_over(old, new)
    assert kept == {1: 1, 2: 2}
    assert new[0]["chapter_break"] == 1  # translations follow through the id map
    assert new[0]["text"] == "Hello there." and new[0]["speaker"] == "B"  # reviewed: the person's version wins
    assert new[1].get("reviewed") == 0


def test_unreviewed_line_takes_the_new_text_and_speaker():
    old = [row(1, 0.0, 2.0, "old words")]
    new = [{"id": 1, "start": 0.1, "end": 2.0, "text": "new words", "speaker": "C"}]
    carry_over(old, new)
    assert new[0]["text"] == "new words" and new[0]["speaker"] == "C"


def test_lines_that_changed_shape_are_not_matched():
    old = [row(1, 0.0, 6.0, chapter=1)]
    new = [{"id": 1, "start": 0.0, "end": 2.0, "text": "a"}, {"id": 2, "start": 2.0, "end": 6.0, "text": "b"}]
    kept = carry_over(old, new)
    # The 4 s half overlaps 67% of the old span: it inherits; the 2 s half does not.
    assert kept == {1: 2} and "chapter_break" not in new[0]


def test_each_old_line_is_used_once():
    old = [row(1, 0.0, 2.0)]
    new = [{"id": 1, "start": 0.0, "end": 2.0, "text": "a"}, {"id": 2, "start": 0.1, "end": 2.0, "text": "b"}]
    assert carry_over(old, new) == {1: 1}
