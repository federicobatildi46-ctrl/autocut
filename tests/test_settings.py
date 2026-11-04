import pytest

from autocut.settings import (
    SettingsError,
    parse_set,
    profile_for_orientation,
    resolve_settings,
)


def test_long_profile_defaults():
    s = resolve_settings("long", profile_source="auto")
    assert (s.pauses.threshold_ms, s.pauses.margin_ms) == (1000, 150)
    assert s.profile == "long" and s.profile_source == "auto"
    assert s.transcription.model == "scribe_v2"
    assert s.transcription.language == "ita"


def test_short_profile_defaults():
    s = resolve_settings("short")
    assert (s.pauses.threshold_ms, s.pauses.margin_ms) == (800, 150)
    assert s.repeats.complete_coverage == 0.85


def test_layers_project_then_cli():
    project = {"pauses": {"threshold_ms": 900}, "repeats": {"min_tokens": 4}}
    s = resolve_settings("long", project_settings=project, sets=["pauses.threshold_ms=700"])
    assert s.pauses.threshold_ms == 700  # --set vince sul progetto
    assert s.pauses.margin_ms == 150  # non toccato
    assert s.repeats.min_tokens == 4  # dal progetto


def test_set_parses_json_values_and_falls_back_to_strings():
    assert parse_set("pauses.margin_ms=200") == {"pauses": {"margin_ms": 200}}
    assert parse_set("transcription.language=eng") == {"transcription": {"language": "eng"}}
    assert parse_set("repeats.similarity_min=0.7") == {"repeats": {"similarity_min": 0.7}}


@pytest.mark.parametrize("expr", ["senza_uguale", "=5", "pauses..x=1"])
def test_set_rejects_malformed(expr):
    with pytest.raises(SettingsError):
        parse_set(expr)


def test_typos_are_errors_not_silently_ignored():
    with pytest.raises(SettingsError, match="pauses.treshold_ms"):
        resolve_settings("long", sets=["pauses.treshold_ms=900"])


def test_wrong_types_are_rejected():
    with pytest.raises(ValueError):
        resolve_settings("long", sets=["pauses.threshold_ms=tanto"])


def test_profile_cannot_be_set_via_set():
    with pytest.raises(SettingsError, match="--profile"):
        resolve_settings("long", sets=["profile=short"])


def test_unknown_profile():
    with pytest.raises(SettingsError, match="disponibili: long, short"):
        resolve_settings("medio")


def test_profile_from_orientation():
    assert profile_for_orientation("landscape") == "long"
    assert profile_for_orientation("portrait") == "short"
    with pytest.raises(SettingsError):
        profile_for_orientation("diagonale")
