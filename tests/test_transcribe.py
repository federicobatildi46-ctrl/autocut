"""Trascrizione senza API né file veri: trasporto HTTP finto ed estrazione audio finta."""

import json
from pathlib import Path

import httpx
import pytest

from autocut.ingest.step import run_ingest
from autocut.transcribe import cache
from autocut.transcribe.scribe import ScribeError, ScribeRequest, transcribe_file
from autocut.transcribe.step import TranscribeError, run_transcribe
from autocut.transcribe.words import words_from_response
from tests.fakes import iphone_ffprobe
from tests.test_ingest_step import IPHONE, fake_probe

RESPONSE = {
    "language_code": "ita",
    "language_probability": 0.98765,
    "text": "Ciao a tutti (risata)",
    "words": [
        {"text": "Ciao", "type": "word", "start": 1.2, "end": 1.48, "logprob": -0.01},
        {"text": " ", "type": "spacing", "start": 1.48, "end": 1.52, "logprob": 0.0},
        {"text": "a", "type": "word", "start": 1.52, "end": 1.6, "logprob": -0.2},
        {"text": " ", "type": "spacing", "start": 1.6, "end": 3.58, "logprob": 0.0},
        {"text": "tutti", "type": "word", "start": 3.58, "end": 4.05, "logprob": -0.05},
        {"text": "(risata)", "type": "audio_event", "start": 4.2, "end": 4.9, "logprob": -0.3},
        {"text": "boh", "type": "word", "start": None, "end": None, "logprob": -1.0},
    ],
}


# --- conversione ------------------------------------------------------------------------


def test_words_skip_spacing_and_missing_times():
    words = words_from_response(RESPONSE)
    assert [w.text for w in words] == ["Ciao", "a", "tutti", "(risata)"]
    assert [w.id for w in words] == ["w000001", "w000002", "w000003", "w000004"]
    assert (words[0].start_ms, words[0].end_ms) == (1200, 1480)
    assert words[3].kind == "audio_event"
    assert words[1].logprob == -0.2


def test_words_offset_for_ranges():
    words = words_from_response(RESPONSE, offset_ms=60000)
    assert (words[0].start_ms, words[0].end_ms) == (61200, 61480)


def test_words_are_sorted_and_end_never_before_start():
    resp = {
        "words": [
            {"text": "dopo", "type": "word", "start": 2.0, "end": 2.5, "logprob": 0},
            {"text": "prima", "type": "word", "start": 1.0, "end": 0.9, "logprob": 0},
        ]
    }
    words = words_from_response(resp)
    assert [w.text for w in words] == ["prima", "dopo"]
    assert words[0].end_ms == words[0].start_ms == 1000


# --- cache ---------------------------------------------------------------------------------


def _key(**over):
    args = {
        "fingerprint": "fp1:aaa",
        "rng": None,
        "extract_params": {"map": "0:a:0"},
        "request_params": ScribeRequest("scribe_v2", "ita").params(),
    }
    args.update(over)
    return cache.cache_key(**args)


def test_cache_key_is_stable_and_sensitive():
    assert _key() == _key()
    assert _key(fingerprint="fp1:bbb") != _key()
    assert _key(request_params=ScribeRequest("scribe_v2", "eng").params()) != _key()
    assert _key(extract_params={"map": "0:a:1"}) != _key()


# --- client HTTP -------------------------------------------------------------------------


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_request_shape(tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"fLaC")
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers["xi-api-key"]
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json=RESPONSE)

    data = transcribe_file(
        audio, ScribeRequest("scribe_v2", "ita"), api_key="k", client=_client(handler)
    )
    assert data["language_code"] == "ita"
    assert seen["key"] == "k"
    assert seen["url"] == "https://api.elevenlabs.io/v1/speech-to-text"
    body = seen["body"]
    for field, value in [
        ("model_id", b"scribe_v2"),
        ("language_code", b"ita"),
        ("timestamps_granularity", b"word"),
        ("tag_audio_events", b"true"),
        ("diarize", b"false"),
        ("temperature", b"0.0"),
        ("seed", b"0"),
    ]:
        assert f'name="{field}"'.encode() in body
        assert value in body
    assert b'name="file"; filename="a.flac"' in body


def test_retries_on_server_errors(tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503 if len(calls) == 1 else 200, json=RESPONSE)

    transcribe_file(
        audio,
        ScribeRequest("scribe_v2", "ita"),
        api_key="k",
        client=_client(handler),
        sleep=lambda s: None,
    )
    assert len(calls) == 2


@pytest.mark.parametrize(("status", "match"), [(401, "chiave"), (422, "422")])
def test_errors_are_explained(tmp_path, status, match):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    client = _client(lambda r: httpx.Response(status, json={"detail": "no"}))
    with pytest.raises(ScribeError, match=match):
        transcribe_file(audio, ScribeRequest("scribe_v2", "ita"), api_key="k", client=client)


# --- passo completo --------------------------------------------------------------------


@pytest.fixture
def project(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / IPHONE).write_bytes(b"camera" * 1000)
    root = tmp_path / "projects"
    probe = fake_probe({IPHONE: iphone_ffprobe(rotation=-90)})
    return raw, root, probe


class Api:
    def __init__(self):
        self.calls = 0

    def client(self):
        def handler(request):
            self.calls += 1
            return httpx.Response(200, json=RESPONSE)

        return _client(handler)


def fake_extract(src: Path, dest: Path, *, rng=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fLaC")
    return dest


def test_transcribe_writes_words_and_caches(project):
    raw, root, probe = project
    run_ingest("reel", raw, projects_root=root, probe_fn=probe)
    api = Api()

    res = run_transcribe(
        "reel", projects_root=root, api_key="k", client=api.client(), extract_fn=fake_extract
    )
    assert api.calls == 1 and not res.from_cache
    tl = res.timeline
    assert [w.text for w in tl.words] == ["Ciao", "a", "tutti", "(risata)"]
    assert tl.transcript is not None
    assert tl.transcript.word_count == 4
    assert (tl.transcript.language_code, tl.transcript.language_probability) == ("ita", 0.9877)
    assert set(tl.run.steps) == {"ingest", "transcribe"}
    assert res.cache_path.exists()
    stored = json.loads(res.cache_path.read_text(encoding="utf-8"))
    assert stored["cache_key"] == tl.transcript.cache_key
    first_bytes = res.timeline_path.read_bytes()

    again = run_transcribe(
        "reel", projects_root=root, api_key="k", client=api.client(), extract_fn=fake_extract
    )
    assert api.calls == 1 and again.from_cache  # non si ripaga
    assert again.timeline_path.read_bytes() == first_bytes  # deterministico

    run_transcribe(
        "reel",
        projects_root=root,
        api_key="k",
        client=api.client(),
        extract_fn=fake_extract,
        force=True,
    )
    assert api.calls == 2


def test_cache_survives_without_api_key(project, monkeypatch):
    raw, root, probe = project
    run_ingest("reel", raw, projects_root=root, probe_fn=probe)
    run_transcribe(
        "reel", projects_root=root, api_key="k", client=Api().client(), extract_fn=fake_extract
    )
    monkeypatch.setattr("autocut.transcribe.step.env_api_key", lambda: None)
    assert run_transcribe("reel", projects_root=root, extract_fn=fake_extract).from_cache


def test_missing_api_key(project, monkeypatch):
    raw, root, probe = project
    run_ingest("reel", raw, projects_root=root, probe_fn=probe)
    monkeypatch.setattr("autocut.transcribe.step.env_api_key", lambda: None)
    with pytest.raises(ScribeError, match="ELEVENLABS_API_KEY mancante"):
        run_transcribe("reel", projects_root=root, extract_fn=fake_extract)


def test_range_times_are_absolute(project):
    raw, root, probe = project
    run_ingest("reel", raw, range_text="60-120", projects_root=root, probe_fn=probe)
    res = run_transcribe(
        "reel",
        range_text="60-120",
        projects_root=root,
        api_key="k",
        client=Api().client(),
        extract_fn=fake_extract,
    )
    assert res.timeline_path.parent.name == "reel__range_60-120"
    assert res.timeline.words[0].start_ms == 61200
    assert res.timeline.transcript is not None
    assert res.timeline.transcript.audio_range == res.timeline.run.range


def test_changed_camera_file_is_detected(project):
    raw, root, probe = project
    run_ingest("reel", raw, projects_root=root, probe_fn=probe)
    (raw / IPHONE).write_bytes(b"altro")
    with pytest.raises(TranscribeError, match="cambiato"):
        run_transcribe("reel", projects_root=root, api_key="k", extract_fn=fake_extract)


def test_needs_ingest_first(tmp_path):
    with pytest.raises(TranscribeError, match="lancia prima ingest"):
        run_transcribe("niente", projects_root=tmp_path, api_key="k")
