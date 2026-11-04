import json

import pytest
from pydantic import ValidationError

from autocut.models import OverridesFile
from autocut.models.io import dumps, read_model, write_model


def test_example_round_trips(overrides_dict, tmp_path):
    ov = OverridesFile.model_validate(overrides_dict)
    path = tmp_path / "overrides.json"
    write_model(path, ov)
    again = read_model(path, OverridesFile)
    assert again == ov
    assert json.loads(dumps(again))["overrides"].keys() == overrides_dict["overrides"].keys()


def _invalid(data, match):
    with pytest.raises(ValidationError, match=match):
        OverridesFile.model_validate(data)


def test_key_must_match_target_id(overrides_dict):
    overrides_dict["overrides"]["altro"] = overrides_dict["overrides"].pop("rg:w000001")
    _invalid(overrides_dict, "diversa da target.id")


def test_override_ids_are_unique(overrides_dict):
    overrides_dict["overrides"]["rg:w000001"]["id"] = "ov_0001"
    _invalid(overrides_dict, "duplicato")


def test_set_state_needs_keep_or_remove(overrides_dict):
    overrides_dict["overrides"]["gap:w000002-w000003"]["value"] = {"state": "forse"}
    _invalid(overrides_dict, "keep|remove")


def test_action_must_match_target_type(overrides_dict):
    overrides_dict["overrides"]["gap:w000002-w000003"]["action"] = "choose_take"
    _invalid(overrides_dict, "solo per i gruppi")


def test_choose_take_null_means_keep_all(overrides_dict):
    overrides_dict["overrides"]["rg:w000001"]["value"] = {"take_id": None}
    ov = OverridesFile.model_validate(overrides_dict)
    assert ov.overrides["rg:w000001"].value["take_id"] is None


def test_choose_take_requires_take_id(overrides_dict):
    overrides_dict["overrides"]["rg:w000001"]["value"] = {}
    _invalid(overrides_dict, "take_id")


def test_unknown_action_is_rejected(overrides_dict):
    overrides_dict["overrides"]["rg:w000001"]["action"] = "manual_range"
    _invalid(overrides_dict, "action")


def test_history_seq_is_contiguous(overrides_dict):
    overrides_dict["history"][1]["seq"] = 3
    _invalid(overrides_dict, "atteso seq 2")


def test_undo_must_point_to_an_earlier_entry(overrides_dict):
    undo = {
        "seq": 3,
        "at": "2026-11-04T15:42:00+01:00",
        "action": "undo",
        "override_id": "ov_0002",
        "target_id": "rg:w000001",
        "before": {"take_id": "take:w000001"},
        "after": None,
        "reverts": None,
    }
    overrides_dict["history"].append(undo)
    _invalid(overrides_dict, "reverts")

    undo["reverts"] = 3
    _invalid(overrides_dict, "voci precedenti")

    undo["reverts"] = 2
    assert OverridesFile.model_validate(overrides_dict).history[-1].reverts == 2


def test_history_timestamps_need_a_timezone(overrides_dict):
    overrides_dict["history"][0]["at"] = "2026-11-04T15:40:12"
    _invalid(overrides_dict, "timezone")
