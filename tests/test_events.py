import pytest

from autocut.events import event_tag, is_dead_event, protects_speech
from autocut.models.timeline import TranscriptionSettings, Word
from autocut.settings import resolve_settings
from autocut.transcribe.words import words_from_response


def _event(text: str) -> Word:
    return Word(id="w000001", text=text, start_ms=0, end_ms=100, kind="audio_event")


def _settings(**over) -> TranscriptionSettings:
    return resolve_settings("short").transcription.model_copy(update=over)


def test_event_tag_normalization():
    assert event_tag("[Esita]") == "esita"
    assert event_tag("(risata)") == "risata"


@pytest.mark.parametrize("text", ["[esita]", "[esitazione]", "(tosse)", "[respiro]", "[pausa]"])
def test_default_dead_events(text):
    assert is_dead_event(_event(text), _settings())


@pytest.mark.parametrize("text", ["(risata)", "[applausi]", "[musica]"])
def test_other_events_protect_speech(text):
    assert not is_dead_event(_event(text), _settings())
    assert protects_speech(_event(text), _settings())


def test_ignore_makes_every_event_dead():
    assert is_dead_event(_event("(risata)"), _settings(audio_events="ignore"))


def test_words_are_never_dead_events():
    word = Word(id="w000001", text="esita", start_ms=0, end_ms=100)
    assert not is_dead_event(word, _settings())


def test_dead_events_can_be_changed_per_project():
    s = resolve_settings("short", sets=['transcription.dead_events=["risata"]']).transcription
    assert is_dead_event(_event("(risata)"), s)
    assert not is_dead_event(_event("[esita]"), s)


def test_isolated_punctuation_is_dropped():
    resp = {
        "words": [
            {"text": "Saluto", "type": "word", "start": 1.0, "end": 1.4, "logprob": 0},
            {"text": ".", "type": "word", "start": 1.4, "end": 1.4, "logprob": 0},
            {"text": "…", "type": "word", "start": 1.5, "end": 1.6, "logprob": 0},
            {"text": "25", "type": "word", "start": 2.0, "end": 2.3, "logprob": 0},
            {"text": "l'agenzia", "type": "word", "start": 2.4, "end": 2.9, "logprob": 0},
        ]
    }
    assert [w.text for w in words_from_response(resp)] == ["Saluto", "25", "l'agenzia"]
