"""Passo `ingest`: legge la cartella raw, riconosce camera/schermo, scrive la prima timeline.

I file raw sono solo letti (ffprobe + impronta). Tutto l'output va in projects/<nome>/.
Rilanciare ingest ricrea la timeline da zero: i passi successivi vanno rifatti (la
trascrizione resta in cache su disco e non si ripaga).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..models.io import write_model
from ..models.timeline import (
    DetectedFile,
    Detection,
    Engine,
    EngineWarning,
    Project,
    Run,
    Settings,
    Source,
    Sources,
    StepRecord,
    Sync,
    Timeline,
    TimeRange,
)
from ..paths import TIMELINE_FILE, project_dir
from ..settings import load_project_settings, profile_for_orientation, resolve_settings
from ..timeparse import parse_range
from .classify import Assessment, Classification, assess, classify
from .fingerprint import fingerprint
from .probe import ProbeError, ProbeInfo, probe

VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm"}

ProbeFn = Callable[[Path], ProbeInfo]


class IngestError(ValueError):
    pass


@dataclass(frozen=True)
class IngestResult:
    project_dir: Path
    timeline_path: Path
    timeline: Timeline


def list_inputs(folder: Path) -> tuple[list[Path], list[str]]:
    """Video candidati (ordinati per nome, per determinismo) e file ignorati con il motivo."""
    videos: list[Path] = []
    ignored: list[str] = []
    for path in sorted(folder.iterdir(), key=lambda p: (p.name.casefold(), p.name)):
        if path.is_dir():
            continue
        if path.name.startswith("._"):
            ignored.append(f"{path.name}: file di metadati macOS")
        elif path.name.startswith("."):
            ignored.append(f"{path.name}: file nascosto")
        elif path.suffix.lower() not in VIDEO_EXTS:
            ignored.append(f"{path.name}: non è un video")
        else:
            videos.append(path)
    return videos, ignored


def _resolve_input(value: str, folder: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = folder / path
    if not path.is_file():
        raise IngestError(f"file non trovato: {path}")
    return path


def _source(info: ProbeInfo, policy: str) -> Source:
    return Source(
        file_name=info.file_name,
        path_hint=str(info.path.resolve()),
        fingerprint=fingerprint(info.path),
        container=info.container,
        duration_ms=info.duration_ms,
        video=info.video,
        audio=info.audio,
        audio_policy=policy,
    )


def _classify_auto(folder: Path, probe_fn: ProbeFn) -> tuple[Classification, list[str]]:
    videos, ignored = list_inputs(folder)
    assessments: list[Assessment] = []
    for path in videos:
        try:
            assessments.append(assess(probe_fn(path)))
        except ProbeError as exc:
            ignored.append(f"{path.name}: illeggibile ({exc})")
    return classify(assessments), ignored


def _classify_single_file(path: Path, probe_fn: ProbeFn) -> tuple[Classification, list[str]]:
    """Un singolo video passato al posto della cartella: è la camera, senza schermo."""
    if path.suffix.lower() not in VIDEO_EXTS:
        raise IngestError(f"{path.name}: non è un video ({', '.join(sorted(VIDEO_EXTS))})")
    return classify([assess(probe_fn(path))]), []


def _classify_manual(
    folder: Path, camera: str, screen: str | None, probe_fn: ProbeFn
) -> tuple[Classification, list[str]]:
    """Scelta esplicita: la cartella non viene scansionata, si usa solo ciò che è indicato."""
    cam_path = _resolve_input(camera, folder)
    scr_path = _resolve_input(screen, folder) if screen else None
    if scr_path is not None and scr_path.resolve() == cam_path.resolve():
        raise IngestError("--camera e --screen indicano lo stesso file")
    cam = assess(probe_fn(cam_path))
    scr = assess(probe_fn(scr_path)) if scr_path else None
    return Classification(camera=cam, screen=scr), []


def _input_hash(sources: Sources, settings: Settings, rng: TimeRange | None) -> str:
    payload = {
        "camera": sources.camera.fingerprint,
        "screen": sources.screen.fingerprint if sources.screen else None,
        "settings": settings.model_dump(mode="json"),
        "range": rng.model_dump(mode="json") if rng else None,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def run_ingest(
    name: str,
    raw: Path,
    *,
    camera: str | None = None,
    screen: str | None = None,
    profile: str | None = None,
    sets: Sequence[str] = (),
    range_text: str | None = None,
    projects_root: Path | None = None,
    probe_fn: ProbeFn = probe,
) -> IngestResult:
    """`raw` è la cartella dei file raw, oppure direttamente il video della camera."""
    raw = Path(raw)
    if not raw.exists():
        raise IngestError(f"cartella o file raw non trovato: {raw}")
    if screen and not camera:
        raise IngestError("--screen richiede anche --camera")
    if raw.is_file() and (camera or screen):
        raise IngestError("con --camera/--screen indica una cartella, non un file")

    rng = parse_range(range_text) if range_text else None
    pdir = project_dir(name, rng, projects_root)

    if raw.is_file():
        classification, ignored = _classify_single_file(raw, probe_fn)
        mode = "auto"
    elif camera:
        classification, ignored = _classify_manual(raw, camera, screen, probe_fn)
        mode = "manual"
    else:
        classification, ignored = _classify_auto(raw, probe_fn)
        mode = "auto"

    cam_info = classification.camera.info
    if cam_info.audio is None:
        raise IngestError(f"la camera {cam_info.file_name} non ha una traccia audio")
    if rng and rng.end_ms > cam_info.duration_ms:
        raise IngestError(
            f"--range finisce a {rng.end_ms} ms, oltre la durata della camera "
            f"({cam_info.duration_ms} ms)"
        )

    warnings = [
        EngineWarning(id=f"warn:{t}", type=t, message=m) for t, m in classification.warnings
    ]

    sources = Sources(
        camera=_source(cam_info, "reference"),
        screen=_source(classification.screen.info, "sync_only_mute")
        if classification.screen
        else None,
    )
    if sources.camera.video.fps_mode == "vfr":
        warnings.append(
            EngineWarning(
                id="warn:camera_vfr",
                type="camera_vfr",
                message="la camera è a frame rate variabile: i tagli andranno allineati ai frame",
            )
        )
    if sources.screen is not None and sources.screen.audio is None:
        warnings.append(
            EngineWarning(
                id="warn:screen_no_audio",
                type="screen_no_audio",
                message="lo schermo non ha audio: la sincronizzazione automatica non è possibile",
            )
        )

    def detected(a: Assessment | None, role: str, flag: str) -> DetectedFile | None:
        if a is None:
            return None
        signals = a.signal_names(role)
        return DetectedFile(
            file_name=a.info.file_name, signals=[flag, *signals] if mode == "manual" else signals
        )

    detection = Detection(
        mode=mode,
        camera=detected(classification.camera, "camera", "--camera"),
        screen=detected(classification.screen, "screen", "--screen"),
        ignored=ignored,
        ambiguity=None,
    )

    if profile:
        chosen_profile, source_kind = profile, "cli"
    else:
        chosen_profile = profile_for_orientation(sources.camera.video.orientation)
        source_kind = "auto"
    settings = resolve_settings(
        chosen_profile,
        profile_source=source_kind,
        project_settings=load_project_settings(pdir),
        sets=sets,
    )

    timeline = Timeline(
        engine=Engine(name="autocut", version=__version__),
        project=Project(name=name),
        run=Run(
            range=rng,
            steps={"ingest": StepRecord(input_hash=_input_hash(sources, settings, rng))},
        ),
        detection=detection,
        sources=sources,
        sync=Sync(status="pending" if sources.screen else "not_applicable"),
        settings=settings,
        warnings=warnings,
    )
    path = pdir / TIMELINE_FILE
    write_model(path, timeline)
    return IngestResult(project_dir=pdir, timeline_path=path, timeline=timeline)
