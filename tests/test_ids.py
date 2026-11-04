import pytest

from autocut import ids


def test_word_id_is_zero_padded_and_one_based():
    assert ids.word_id(1) == "w000001"
    assert ids.word_id(1234567) == "w1234567"
    with pytest.raises(ValueError):
        ids.word_id(0)


def test_gap_ids_use_head_and_tail_markers():
    assert ids.gap_id(None, "w000001") == "gap:^-w000001"
    assert ids.gap_id("w000002", "w000003") == "gap:w000002-w000003"
    assert ids.gap_id("w000005", None) == "gap:w000005-$"
    assert ids.gap_id(None, None) == "gap:^-$"  # nessun parlato


def test_decision_ids_are_anchored_to_words():
    assert ids.segment_id("w000003", "w000005") == "seg:w000003-w000005"
    assert ids.group_id("w000001") == "rg:w000001"
    assert ids.take_id("w000003") == "take:w000003"
    assert ids.proposal_id("rg:w000001") == "prop:rg:w000001"


@pytest.mark.parametrize(
    ("identifier", "kind"),
    [
        ("w000001", "w"),
        ("gap:^-w000001", "gap"),
        ("seg:w000001-w000002", "seg"),
        ("rg:w000001", "rg"),
        ("take:w000001", "take"),
        ("prop:rg:w000001", "prop"),
    ],
)
def test_kind_of(identifier, kind):
    assert ids.kind_of(identifier) == kind


def test_kind_of_rejects_garbage():
    with pytest.raises(ValueError):
        ids.kind_of("qualcosa")
