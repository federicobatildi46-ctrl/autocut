"""Modelli di timeline.json: unica definizione dello schema (lo JSON Schema è generato da qui).

Regola di estendibilità: i campi sconosciuti sono ammessi e ignorati, così i passi futuri
(stili, grafiche, video di riferimento) possono aggiungere sezioni senza rompere i lettori.
Solo le modifiche incompatibili incrementano SCHEMA_VERSION.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

Ms = int  # millisecondi interi sull'asse master (tempo della camera)


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


def _check_span(start_ms: int, end_ms: int, what: str) -> None:
    if start_ms < 0:
        raise ValueError(f"{what}: start_ms negativo")
    if end_ms < start_ms:
        raise ValueError(f"{what}: end_ms < start_ms")


# --- metadati ---------------------------------------------------------------


class Engine(_Model):
    name: str
    version: str


class Project(_Model):
    name: str


class TimeBase(_Model):
    unit: Literal["ms"] = "ms"
    master: Literal["camera"] = "camera"


class TimeRange(_Model):
    start_ms: Ms
    end_ms: Ms

    @model_validator(mode="after")
    def _span(self) -> TimeRange:
        _check_span(self.start_ms, self.end_ms, "range")
        return self


class StepRecord(_Model):
    input_hash: str


class Run(_Model):
    range: TimeRange | None = None
    steps: dict[str, StepRecord] = Field(default_factory=dict)


# --- riconoscimento e sorgenti -----------------------------------------------


class DetectedFile(_Model):
    file_name: str
    signals: list[str] = Field(default_factory=list)


class Detection(_Model):
    mode: Literal["auto", "manual"]
    camera: DetectedFile
    screen: DetectedFile | None = None
    ignored: list[str] = Field(default_factory=list)
    ambiguity: str | None = None


class VideoStream(_Model):
    codec: str
    coded_width: int
    coded_height: int
    rotation: int = 0
    display_width: int
    display_height: int
    orientation: Literal["landscape", "portrait", "square"]
    fps: float
    fps_mode: Literal["cfr", "vfr"]
    start_ms: int = 0


class AudioStream(_Model):
    codec: str
    sample_rate: int
    channels: int
    start_ms: int = 0


class Source(_Model):
    file_name: str
    path_hint: str | None = None
    fingerprint: str
    container: str
    duration_ms: Ms
    video: VideoStream
    audio: AudioStream | None = None
    audio_policy: Literal["reference", "sync_only_mute"]


class Sources(_Model):
    camera: Source
    screen: Source | None = None


# --- sincronizzazione --------------------------------------------------------


class DriftSample(_Model):
    camera_ms: Ms
    origin_ms: int


class Drift(_Model):
    measured: bool
    window_ms: int | None = None
    ppm: float | None = None
    max_dev_ms: int | None = None
    status: Literal["ok", "warn", "not_measured"]
    samples: list[DriftSample] = Field(default_factory=list)


class Sync(_Model):
    status: Literal["pending", "not_applicable", "ok", "low_confidence", "failed"]
    method: str | None = None
    screen_origin_ms: int | None = Field(
        default=None, description="Istante sull'asse camera in cui cade lo 0 del file schermo."
    )
    confidence: float | None = None
    mapping: str | None = None
    drift: Drift | None = None


# --- impostazioni effettive -------------------------------------------------


class PauseSettings(_Model):
    threshold_ms: int = Field(ge=0)
    margin_ms: int = Field(ge=0)


class RepeatSettings(_Model):
    unit_gap_ms: int = Field(ge=0)
    min_tokens: int = Field(ge=1)
    similarity_min: float = Field(ge=0, le=1)
    complete_coverage: float = Field(ge=0, le=1)


class TranscriptionSettings(_Model):
    provider: str
    model: str
    language: str
    audio_events: Literal["keep", "ignore"]
    # Con audio_events="keep": eventi che NON proteggono il parlato (confronto per sottostringa
    # sul tag minuscolo senza parentesi, es. "[esita]" -> "esita").
    dead_events: list[str] = Field(default_factory=list)


class SyncSettings(_Model):
    max_lag_ms: int = Field(ge=0)
    drift_window_ms: int = Field(gt=0)


class Settings(_Model):
    profile: str
    profile_source: Literal["auto", "cli"]
    pauses: PauseSettings
    repeats: RepeatSettings
    transcription: TranscriptionSettings
    sync: SyncSettings


# --- trascrizione -------------------------------------------------------------


class Transcript(_Model):
    cache_key: str
    audio_range: TimeRange | None = None
    word_count: int = Field(ge=0)
    language_code: str | None = None  # lingua rilevata da Scribe
    language_probability: float | None = None


class Word(_Model):
    id: str
    text: str
    start_ms: Ms
    end_ms: Ms
    kind: Literal["word", "audio_event"] = "word"  # audio_event = risata, rumore, ...
    logprob: float | None = None  # confidenza di Scribe (<= 0)

    @model_validator(mode="after")
    def _span(self) -> Word:
        _check_span(self.start_ms, self.end_ms, f"parola {self.id}")
        return self


# --- decisioni: segmenti ----------------------------------------------------


class Segment(_Model):
    id: str
    state: Literal["keep", "remove"]
    type: Literal["speech", "dead_pause"]
    start_ms: Ms
    end_ms: Ms
    reason: str
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _span(self) -> Segment:
        _check_span(self.start_ms, self.end_ms, f"segmento {self.id}")
        return self


# --- decisioni: ripetizioni -------------------------------------------------


class DiffOp(_Model):
    op: Literal["missing", "extra", "replace"]
    text: str
    other_text: str | None = None


class Take(_Model):
    id: str
    index: int = Field(ge=1)
    start_ms: Ms
    end_ms: Ms
    text: str
    word_span: tuple[str, str] = Field(description="Prima e ultima parola della presa.")
    status: Literal["complete", "false_start"]
    coverage: float = Field(ge=0, le=1)
    similarity_to_compared: float = Field(ge=0, le=1)
    diff_vs_compared: list[DiffOp] = Field(default_factory=list)

    @model_validator(mode="after")
    def _span(self) -> Take:
        _check_span(self.start_ms, self.end_ms, f"presa {self.id}")
        return self


class Similarity(_Model):
    min: float = Field(ge=0, le=1)
    mean: float = Field(ge=0, le=1)


class Proposal(_Model):
    id: str
    type: Literal["repeat_choice"] = "repeat_choice"
    take_id: str
    rule: str
    reason: str


class RepeatGroup(_Model):
    id: str
    status: Literal["proposed", "ambiguous"]
    similarity: Similarity
    compared_to: str = Field(
        description=(
            "Presa di confronto per similarità e diff: la proposta, o la più lunga se ambiguo."
        )
    )
    takes: list[Take] = Field(min_length=2)
    proposal: Proposal | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _consistency(self) -> RepeatGroup:
        by_id = {t.id: t for t in self.takes}
        if self.compared_to not in by_id:
            raise ValueError(f"gruppo {self.id}: compared_to non è una presa del gruppo")
        if self.status == "ambiguous":
            if self.proposal is not None:
                raise ValueError(f"gruppo {self.id}: un gruppo ambiguo non ha proposta")
            if not self.reason:
                raise ValueError(f"gruppo {self.id}: un gruppo ambiguo deve avere un motivo")
        else:
            if self.proposal is None:
                raise ValueError(f"gruppo {self.id}: manca la proposta")
            chosen = by_id.get(self.proposal.take_id)
            if chosen is None:
                raise ValueError(f"gruppo {self.id}: la proposta punta a una presa assente")
            if chosen.status != "complete":
                raise ValueError(f"gruppo {self.id}: una falsa partenza non può essere proposta")
        return self


# --- varie -------------------------------------------------------------------


class EngineWarning(_Model):
    id: str
    type: str
    message: str


class Stats(_Model):
    raw_ms: Ms
    kept_ms: Ms
    removed_ms: Ms
    repeat_groups: int = Field(ge=0)
    ambiguous_groups: int = Field(ge=0)


# --- radice ------------------------------------------------------------------


class Timeline(_Model):
    model_config = ConfigDict(extra="allow", title="autocut timeline")

    schema_version: int = SCHEMA_VERSION
    engine: Engine
    project: Project
    time_base: TimeBase = Field(default_factory=TimeBase)
    run: Run = Field(default_factory=Run)
    detection: Detection
    sources: Sources
    sync: Sync
    settings: Settings
    transcript: Transcript | None = None
    words: list[Word] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    repeat_groups: list[RepeatGroup] = Field(default_factory=list)
    warnings: list[EngineWarning] = Field(default_factory=list)
    stats: Stats | None = None

    @field_validator("schema_version")
    @classmethod
    def _supported(cls, v: int) -> int:
        if v != SCHEMA_VERSION:
            raise ValueError(f"schema_version {v} non supportata (supportata: {SCHEMA_VERSION})")
        return v

    @model_validator(mode="after")
    def _integrity(self) -> Timeline:
        seen: set[str] = set()

        def claim(identifier: str) -> None:
            if identifier in seen:
                raise ValueError(f"id duplicato: {identifier}")
            seen.add(identifier)

        word_ids: list[str] = []
        for w in self.words:
            claim(w.id)
            word_ids.append(w.id)
        for prev, cur in zip(self.words, self.words[1:], strict=False):
            if cur.start_ms < prev.start_ms:
                raise ValueError(f"parole non in ordine: {prev.id} -> {cur.id}")
        position = {wid: i for i, wid in enumerate(word_ids)}

        for s in self.segments:
            claim(s.id)
        for prev, cur in zip(self.segments, self.segments[1:], strict=False):
            if cur.start_ms != prev.end_ms:
                raise ValueError(
                    f"segmenti non contigui: {prev.id} finisce a {prev.end_ms}, "
                    f"{cur.id} inizia a {cur.start_ms}"
                )

        for g in self.repeat_groups:
            claim(g.id)
            if g.proposal is not None:
                claim(g.proposal.id)
            for t in g.takes:
                claim(t.id)
                first, last = t.word_span
                if first not in position or last not in position:
                    raise ValueError(f"presa {t.id}: word_span punta a parole assenti")
                if position[first] > position[last]:
                    raise ValueError(f"presa {t.id}: word_span invertito")

        if self.transcript is not None and self.transcript.word_count != len(self.words):
            raise ValueError("transcript.word_count diverso dal numero di parole")
        return self
