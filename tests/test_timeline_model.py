import json

import pytest
from pydantic import ValidationError

from autocut.models import Timeline
from autocut.models.io import dumps, read_model, write_model


def test_example_round_trips_exactly(timeline_dict):
    tl = Timeline.model_validate(timeline_dict)
    assert json.loads(dumps(tl)) == timeline_dict


def test_dump_is_deterministic(timeline_dict, tmp_path):
    tl = Timeline.model_validate(timeline_dict)
    path = tmp_path / "timeline.json"
    write_model(path, tl)
    first = path.read_bytes()
    write_model(path, read_model(path, Timeline))
    assert path.read_bytes() == first
    assert first.endswith(b"\n") and b"\r\n" not in first


def test_camera_only_project(timeline_dict):
    timeline_dict["sources"]["screen"] = None
    timeline_dict["detection"]["screen"] = None
    timeline_dict["sync"] = {"status": "not_applicable"}
    tl = Timeline.model_validate(timeline_dict)
    assert tl.sources.screen is None
    assert tl.sync.drift is None


def test_unknown_sections_are_preserved(timeline_dict):
    timeline_dict["styles"] = {"preset": "futuro"}
    tl = Timeline.model_validate(timeline_dict)
    assert json.loads(dumps(tl))["styles"] == {"preset": "futuro"}


def _invalid(timeline_dict, match):
    with pytest.raises(ValidationError, match=match):
        Timeline.model_validate(timeline_dict)


def test_rejects_unsupported_schema_version(timeline_dict):
    timeline_dict["schema_version"] = 2
    _invalid(timeline_dict, "non supportata")


def test_rejects_duplicate_ids(timeline_dict):
    timeline_dict["segments"][1]["id"] = "gap:^-w000001"
    _invalid(timeline_dict, "id duplicato")


def test_rejects_non_contiguous_segments(timeline_dict):
    timeline_dict["segments"][1]["start_ms"] = 1100
    _invalid(timeline_dict, "non contigui")


def test_rejects_inverted_span(timeline_dict):
    timeline_dict["words"][0]["end_ms"] = 1000
    _invalid(timeline_dict, "end_ms < start_ms")


def test_rejects_take_pointing_to_missing_words(timeline_dict):
    timeline_dict["repeat_groups"][0]["takes"][0]["word_span"] = ["w000001", "w000099"]
    _invalid(timeline_dict, "parole assenti")


def test_rejects_word_count_mismatch(timeline_dict):
    timeline_dict["transcript"]["word_count"] = 4
    _invalid(timeline_dict, "word_count")


def test_false_start_can_never_be_proposed(timeline_dict):
    group = timeline_dict["repeat_groups"][0]
    group["proposal"]["take_id"] = "take:w000001"
    _invalid(timeline_dict, "falsa partenza")


def test_ambiguous_group_has_reason_and_no_proposal(timeline_dict):
    group = timeline_dict["repeat_groups"][0]
    group["status"] = "ambiguous"
    _invalid(timeline_dict, "non ha proposta")

    group["proposal"] = None
    _invalid(timeline_dict, "motivo")

    group["reason"] = "nessuna presa completa nel gruppo"
    tl = Timeline.model_validate(timeline_dict)
    assert tl.repeat_groups[0].proposal is None


def test_group_needs_at_least_two_takes(timeline_dict):
    group = timeline_dict["repeat_groups"][0]
    group["takes"] = group["takes"][1:]
    _invalid(timeline_dict, "at least 2")
