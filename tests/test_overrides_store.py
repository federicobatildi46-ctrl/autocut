"""Override: correzioni, cronologia, undo, orfani e vista effettiva (dati finti)."""

import pytest

from autocut.models import OverridesFile, Timeline
from autocut.overrides import store
from autocut.overrides.resolve import effective_ranges, kept_ms

GAP = "gap:w000002-w000003"
GROUP = "rg:w000001"


@pytest.fixture
def tl(timeline_dict) -> Timeline:
    return Timeline.model_validate(timeline_dict)


@pytest.fixture
def empty(tl, tmp_path) -> OverridesFile:
    return store.load(tmp_path, tl)


def test_new_file_points_to_the_project(empty):
    assert empty.timeline_ref.project == "episodio-12"
    assert empty.overrides == {} and empty.history == []


def test_flip_a_pause_and_history(empty, tl):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    o = ov.overrides[GAP]
    assert (o.id, o.action, o.value, o.proposed) == (
        "ov_0001",
        "set_state",
        {"state": "keep"},
        {"state": "remove"},
    )
    assert o.snapshot["start_ms"] == 1750
    h = ov.history[-1]
    assert (h.seq, h.action, h.target_id, h.before, h.after) == (
        1,
        "create",
        GAP,
        None,
        {"state": "keep"},
    )
    assert h.at.tzinfo is not None


def test_setting_the_proposal_back_removes_the_override(empty, tl):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    ov = store.set_value(ov, tl, GAP, {"state": "remove"})
    assert GAP not in ov.overrides
    assert [e.action for e in ov.history] == ["create", "remove"]


def test_same_value_twice_is_a_no_op(empty, tl):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    assert store.set_value(ov, tl, GAP, {"state": "keep"}) is ov


def test_unknown_target_and_bad_values(empty, tl):
    with pytest.raises(store.OverrideError, match="nessuna proposta"):
        store.set_value(empty, tl, "gap:nope", {"state": "keep"})
    with pytest.raises(store.OverrideError, match="keep"):
        store.set_value(empty, tl, GAP, {"state": "forse"})
    with pytest.raises(store.OverrideError, match="non fa parte"):
        store.set_value(empty, tl, GROUP, {"take_id": "take:w000099"})


def test_choose_another_take(empty, tl):
    ov = store.set_value(empty, tl, GROUP, {"take_id": None})  # tieni tutte le prese
    assert ov.overrides[GROUP].action == "choose_take"
    assert ov.overrides[GROUP].proposed == {"take_id": "take:w000003"}


def test_undo_step_by_step(empty, tl):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})  # 1 create
    ov = store.set_value(ov, tl, GROUP, {"take_id": None})  # 2 create
    ov = store.clear(ov, GAP)  # 3 remove

    ov = store.undo(ov, tl)  # annulla 3: il gap torna "keep"
    assert ov.overrides[GAP].value == {"state": "keep"}
    assert ov.history[-1].reverts == 3

    ov = store.undo(ov, tl)  # annulla 2
    assert GROUP not in ov.overrides
    ov = store.undo(ov, tl)  # annulla 1
    assert ov.overrides == {}
    assert [e.action for e in ov.history] == ["create", "create", "remove", "undo", "undo", "undo"]
    with pytest.raises(store.OverrideError, match="niente da annullare"):
        store.undo(ov, tl)

    # il file con la cronologia completa resta valido (seq contigui, reverts precedenti)
    OverridesFile.model_validate(ov.model_dump(mode="json"))


def test_new_action_after_undo_is_undone_first(empty, tl):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    ov = store.undo(ov, tl)
    ov = store.set_value(ov, tl, GROUP, {"take_id": None})
    ov = store.undo(ov, tl)
    assert ov.overrides == {}
    assert ov.history[-1].reverts == 3


def test_orphan_when_the_proposal_disappears_and_restore(empty, tl, timeline_dict):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})

    gone = dict(timeline_dict)
    seg = timeline_dict["segments"]
    gone["segments"] = [
        seg[0],
        {**seg[1], "id": "seg:w000001-w000005", "end_ms": 4200},
        seg[4],
    ]
    gone["segments"][1]["data"] = {"word_span": ["w000001", "w000005"]}
    tl_without = Timeline.model_validate(gone)

    ov, orphaned, restored = store.reconcile(ov, tl_without)
    assert orphaned == [GAP] and restored == []
    assert ov.overrides[GAP].status == "orphan"
    assert ov.history[-1].action == "orphaned"
    # un orfano non si applica alla cieca
    assert not any(r.origin == "override" for r in effective_ranges(tl_without, ov))

    ov, orphaned, restored = store.reconcile(ov, tl)
    assert restored == [GAP] and ov.overrides[GAP].status == "active"
    again, o2, r2 = store.reconcile(ov, tl)
    assert again is ov and o2 == r2 == []


def test_effective_ranges_apply_overrides_and_takes(empty, tl):
    base = effective_ranges(tl, empty)
    # proposta: si toglie la falsa partenza (take:w000001, 1200-1600) dentro il primo keep
    assert [(r.start_ms, r.end_ms, r.state, r.origin) for r in base] == [
        (0, 1050, "remove", "proposal"),
        (1050, 1200, "keep", "proposal"),
        (1200, 1600, "remove", "take"),
        (1600, 1750, "keep", "proposal"),
        (1750, 2950, "remove", "proposal"),
        (2950, 4200, "keep", "proposal"),
        (4200, 5200, "remove", "proposal"),
    ]
    assert all(a.end_ms == b.start_ms for a, b in zip(base, base[1:], strict=False))

    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    ov = store.set_value(ov, tl, GROUP, {"take_id": None})
    eff = effective_ranges(tl, ov)
    assert ("gap:w000002-w000003", "keep", "override") in [
        (r.source_id, r.state, r.origin) for r in eff
    ]
    assert not any(r.origin == "take" for r in eff)
    assert kept_ms(eff) == 700 + 1200 + 1250


def test_save_and_load_round_trip(empty, tl, tmp_path):
    ov = store.set_value(empty, tl, GAP, {"state": "keep"})
    store.save(tmp_path, ov)
    assert store.load(tmp_path, tl) == ov
