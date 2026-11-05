"""Passo `cuts`: dalle parole ai segmenti tenuti/tolti (pause morte).

Le impostazioni usate sono quelle in timeline; `--set` può cambiare solo `pauses.*` e le
regole sugli eventi audio, e il valore effettivo resta registrato nella timeline.
Per renderle permanenti nel progetto: projects/<nome>/settings.json + ingest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..models.io import read_model, write_model
from ..models.timeline import Stats, Timeline
from ..overrides import store as overrides_store
from ..paths import TIMELINE_FILE, project_dir
from ..settings import apply_sets
from ..timeparse import parse_range
from .pauses import compute_segments

CUTS_SETTABLE = ("pauses", "transcription.audio_events", "transcription.dead_events")


class CutsError(ValueError):
    pass


@dataclass(frozen=True)
class CutsResult:
    timeline: Timeline
    timeline_path: Path
    orphaned: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)


def _input_hash(tl: Timeline, axis: tuple[int, int]) -> str:
    s = tl.settings
    payload = {
        "transcript": tl.transcript.cache_key if tl.transcript else None,
        "pauses": s.pauses.model_dump(mode="json"),
        "audio_events": s.transcription.audio_events,
        "dead_events": s.transcription.dead_events,
        "axis": list(axis),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def run_cuts(
    name: str,
    *,
    range_text: str | None = None,
    sets: Sequence[str] = (),
    projects_root: Path | None = None,
) -> CutsResult:
    pdir = project_dir(name, parse_range(range_text) if range_text else None, projects_root)
    tl_path = pdir / TIMELINE_FILE
    if not tl_path.exists():
        raise CutsError(f"nessuna timeline in {pdir}: lancia prima ingest")
    tl = read_model(tl_path, Timeline)
    if tl.transcript is None:
        raise CutsError("manca la trascrizione: lancia prima transcribe")

    settings = apply_sets(tl.settings, sets, CUTS_SETTABLE) if sets else tl.settings
    rng = tl.run.range
    axis = (rng.start_ms, rng.end_ms) if rng else (0, tl.sources.camera.duration_ms)

    segments = compute_segments(
        tl.words,
        axis_start_ms=axis[0],
        axis_end_ms=axis[1],
        pauses=settings.pauses,
        transcription=settings.transcription,
    )
    kept = sum(s.end_ms - s.start_ms for s in segments if s.state == "keep")
    stats = Stats(
        raw_ms=axis[1] - axis[0],
        kept_ms=kept,
        removed_ms=(axis[1] - axis[0]) - kept,
        repeat_groups=len(tl.repeat_groups),
        ambiguous_groups=sum(1 for g in tl.repeat_groups if g.status == "ambiguous"),
    )

    data = tl.model_dump(mode="json")
    data["settings"] = settings.model_dump(mode="json")
    data["segments"] = [s.model_dump(mode="json") for s in segments]
    data["stats"] = stats.model_dump(mode="json")
    provisional = Timeline.model_validate(data)
    data["run"]["steps"]["cuts"] = {"input_hash": _input_hash(provisional, axis)}
    updated = Timeline.model_validate(data)
    write_model(tl_path, updated)

    # Le scelte dell'utente restano in overrides.json: quelle senza più proposta diventano orfane.
    orphaned: list[str] = []
    restored: list[str] = []
    if overrides_store.overrides_path(pdir).exists():
        ov = overrides_store.load(pdir, updated)
        ov, orphaned, restored = overrides_store.reconcile(ov, updated)
        if orphaned or restored:
            overrides_store.save(pdir, ov)
    return CutsResult(timeline=updated, timeline_path=tl_path, orphaned=orphaned, restored=restored)
