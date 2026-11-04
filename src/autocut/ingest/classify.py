"""Riconoscimento camera / schermo a punteggio. Se non è netto, non indovina: si ferma.

Camera (iPhone): tag Apple, modello iPhone, nome IMG_xxxx, container mov, 4K.
Schermo (OBS): nome con data e ora, mkv, encoder OBS/Lavf, nessun metadato mobile,
risoluzione da monitor.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .probe import ProbeInfo

Label = Literal["camera", "screen", "unknown"]

MIN_SCORE = 3  # punteggio minimo per un ruolo
MAX_OTHER = 1  # punteggio massimo ammesso per l'altro ruolo

IMG_NAME = re.compile(r"^IMG_\d+", re.IGNORECASE)
DATETIME_NAME = re.compile(r"\d{4}-\d{2}-\d{2}[ _T]\d{2}[-.]\d{2}[-.]\d{2}")

MOBILE_TAG_KEYS = (
    "com.apple.quicktime.make",
    "com.apple.quicktime.model",
    "com.apple.quicktime.software",
    "com.android.version",
    "com.android.manufacturer",
)

# Risoluzioni tipiche da monitor (non da camera). 3840x2160 manca apposta: è anche l'iPhone.
MONITOR_RESOLUTIONS = {
    (1366, 768), (1440, 900), (1680, 1050), (1920, 1080), (1920, 1200), (2560, 1080),
    (2560, 1440), (2560, 1600), (2880, 1800), (3024, 1964), (3440, 1440), (3456, 2234),
    (5120, 1440),
}  # fmt: skip


@dataclass(frozen=True)
class Signal:
    name: str
    weight: int


@dataclass(frozen=True)
class Assessment:
    info: ProbeInfo
    camera: tuple[Signal, ...]
    screen: tuple[Signal, ...]

    @property
    def camera_score(self) -> int:
        return sum(s.weight for s in self.camera)

    @property
    def screen_score(self) -> int:
        return sum(s.weight for s in self.screen)

    @property
    def label(self) -> Label:
        cam, scr = self.camera_score, self.screen_score
        if cam >= MIN_SCORE and scr <= MAX_OTHER:
            return "camera"
        if scr >= MIN_SCORE and cam <= MAX_OTHER:
            return "screen"
        return "unknown"

    def signal_names(self, role: Label) -> list[str]:
        return [s.name for s in (self.camera if role == "camera" else self.screen)]

    def describe(self) -> str:
        cam = ", ".join(self.signal_names("camera")) or "-"
        scr = ", ".join(self.signal_names("screen")) or "-"
        return (
            f"{self.info.file_name}: {self.label} "
            f"(camera {self.camera_score} [{cam}]; schermo {self.screen_score} [{scr}])"
        )


def has_mobile_metadata(info: ProbeInfo) -> bool:
    return any(k in info.tags for k in MOBILE_TAG_KEYS)


def assess(info: ProbeInfo) -> Assessment:
    tags = info.tags
    w, h = info.video.coded_width, info.video.coded_height
    long_side, short_side = max(w, h), min(w, h)

    camera: list[Signal] = []
    make = tags.get("com.apple.quicktime.make", "")
    if make.strip().lower() == "apple":
        camera.append(Signal("apple.quicktime.make=Apple", 3))
    model = tags.get("com.apple.quicktime.model", "")
    if "iphone" in model.lower():
        camera.append(Signal(f"model={model.strip()}", 2))
    if IMG_NAME.match(info.file_name):
        camera.append(Signal("name~IMG_\\d+", 1))
    if info.container == "mov":
        camera.append(Signal("container=mov", 1))
    if (long_side, short_side) == (3840, 2160):
        camera.append(Signal("3840x2160", 1))

    screen: list[Signal] = []
    if DATETIME_NAME.search(info.file_name):
        screen.append(Signal("name~YYYY-MM-DD HH-MM-SS", 2))
    if info.container == "mkv":
        screen.append(Signal("container=mkv", 2))
    encoder = tags.get("encoder", "")
    if "obs" in encoder.lower():
        screen.append(Signal(f"encoder={encoder.strip()}", 2))
    elif encoder.lower().startswith("lavf"):
        screen.append(Signal("encoder=Lavf", 1))
    if not has_mobile_metadata(info):
        screen.append(Signal("no_mobile_metadata", 1))
    if (w, h) in MONITOR_RESOLUTIONS:
        screen.append(Signal(f"{w}x{h}", 1))

    return Assessment(info=info, camera=tuple(camera), screen=tuple(screen))


@dataclass(frozen=True)
class Classification:
    camera: Assessment
    screen: Assessment | None
    warnings: tuple[tuple[str, str], ...] = ()  # (tipo, messaggio)


class AmbiguousClassification(Exception):
    def __init__(self, reason: str, assessments: Sequence[Assessment]):
        self.reason = reason
        self.assessments = tuple(assessments)
        lines = [reason, *(f"  - {a.describe()}" for a in self.assessments)]
        lines.append("Indica i file con --camera <file> e --screen <file>.")
        super().__init__("\n".join(lines))


def classify(assessments: Sequence[Assessment]) -> Classification:
    """Classificazione automatica di tutti i video della cartella."""
    if not assessments:
        raise AmbiguousClassification("nessun video nella cartella", assessments)

    if len(assessments) == 1:
        only = assessments[0]
        warnings: tuple[tuple[str, str], ...] = ()
        if only.label != "camera":
            warnings = (
                (
                    "single_video_not_camera_like",
                    f"unico video {only.info.file_name} usato come camera, "
                    f"ma non ha l'aspetto di una ripresa iPhone ({only.label})",
                ),
            )
        return Classification(camera=only, screen=None, warnings=warnings)

    cameras = [a for a in assessments if a.label == "camera"]
    screens = [a for a in assessments if a.label == "screen"]
    unknown = [a for a in assessments if a.label == "unknown"]
    if len(cameras) == 1 and len(screens) == 1 and not unknown:
        return Classification(camera=cameras[0], screen=screens[0])

    reason = (
        f"riconoscimento ambiguo: {len(assessments)} video, "
        f"{len(cameras)} camera, {len(screens)} schermo, {len(unknown)} non riconosciuti"
    )
    raise AmbiguousClassification(reason, assessments)
