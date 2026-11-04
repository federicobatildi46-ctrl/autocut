"""Passo `transcribe`: audio della camera -> Scribe -> parole con i tempi nella timeline.

- La trascrizione è in cache (projects/<nome>/transcript/): non si ripaga se il file camera,
  il tratto e i parametri non cambiano. `force=True` la rifà.
- I tempi sono assoluti sull'asse camera anche con --range.
- Rilanciare la trascrizione invalida i passi successivi (tagli, ripetizioni).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..env import API_KEY_VAR
from ..env import api_key as env_api_key
from ..ingest.fingerprint import fingerprint
from ..models.io import read_model, write_model
from ..models.timeline import StepRecord, Timeline, TimeRange, Transcript
from ..paths import TIMELINE_FILE, project_dir
from ..timeparse import parse_range
from . import cache
from .audio import EXTRACT_PARAMS, extract_audio
from .scribe import ScribeError, ScribeRequest, transcribe_file
from .words import words_from_response

DOWNSTREAM_STEPS = ("cuts", "repeats")

ExtractFn = Callable[..., Path]


class TranscribeError(ValueError):
    pass


@dataclass(frozen=True)
class TranscribeResult:
    timeline: Timeline
    timeline_path: Path
    cache_path: Path
    from_cache: bool


def _camera_file(tl: Timeline) -> Path:
    cam = tl.sources.camera
    if not cam.path_hint or not Path(cam.path_hint).is_file():
        raise TranscribeError(
            f"file camera non trovato: {cam.path_hint} (rilancia ingest con il percorso giusto)"
        )
    path = Path(cam.path_hint)
    if fingerprint(path) != cam.fingerprint:
        raise TranscribeError(f"{cam.file_name} è cambiato dall'ingest: rilancia ingest")
    return path


def run_transcribe(
    name: str,
    *,
    range_text: str | None = None,
    force: bool = False,
    projects_root: Path | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    extract_fn: ExtractFn = extract_audio,
    on_upload: Callable[[float], None] | None = None,
) -> TranscribeResult:
    rng_arg = parse_range(range_text) if range_text else None
    pdir = project_dir(name, rng_arg, projects_root)
    tl_path = pdir / TIMELINE_FILE
    if not tl_path.exists():
        raise TranscribeError(f"nessuna timeline in {pdir}: lancia prima ingest")
    tl = read_model(tl_path, Timeline)
    rng: TimeRange | None = tl.run.range

    src = _camera_file(tl)
    settings = tl.settings.transcription
    request = ScribeRequest(model_id=settings.model, language_code=settings.language)
    key = cache.cache_key(
        fingerprint=tl.sources.camera.fingerprint,
        rng=rng,
        extract_params=EXTRACT_PARAMS,
        request_params=request.params(),
    )
    cpath = cache.cache_path(pdir, key)
    response = None if force else cache.load(cpath, key)
    from_cache = response is not None

    if response is None:
        key_value = api_key or env_api_key()
        if not key_value:
            raise ScribeError(f"{API_KEY_VAR} mancante: impostala nell'ambiente o in .env")
        audio_path = pdir / "work" / f"camera-{cache.short(key)}.flac"
        extract_fn(src, audio_path, rng=rng)
        if on_upload:
            span = (rng.end_ms - rng.start_ms) if rng else tl.sources.camera.duration_ms
            on_upload(span / 1000)
        response = transcribe_file(audio_path, request, api_key=key_value, client=client)
        cache.store(cpath, key, request.params(), response)

    offset = (
        rng.start_ms
        if rng
        else (tl.sources.camera.audio.start_ms if tl.sources.camera.audio else 0)
    )
    words = words_from_response(response, offset_ms=offset)
    prob = response.get("language_probability")
    transcript = Transcript(
        cache_key=key,
        audio_range=rng,
        word_count=len(words),
        language_code=response.get("language_code"),
        language_probability=round(float(prob), 4) if prob is not None else None,
    )

    steps = {k: v for k, v in tl.run.steps.items() if k not in DOWNSTREAM_STEPS}
    steps["transcribe"] = StepRecord(input_hash=key)
    data = tl.model_dump(mode="json")
    data.update(
        run={**data["run"], "steps": {k: v.model_dump(mode="json") for k, v in steps.items()}},
        transcript=transcript.model_dump(mode="json"),
        words=[w.model_dump(mode="json") for w in words],
        segments=[],
        repeat_groups=[],
        stats=None,
    )
    updated = Timeline.model_validate(data)  # ricontrolla l'integrità
    write_model(tl_path, updated)
    return TranscribeResult(
        timeline=updated, timeline_path=tl_path, cache_path=cpath, from_cache=from_cache
    )
