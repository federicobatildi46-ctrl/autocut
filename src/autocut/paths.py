"""Dove vivono i progetti. Default: `<repo>/projects/`, sovrascrivibile con AUTOCUT_PROJECTS_DIR."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models.timeline import TimeRange
from .timeparse import format_seconds

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ENV = "AUTOCUT_PROJECTS_DIR"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RANGE_MARK = "__range_"

TIMELINE_FILE = "timeline.json"
OVERRIDES_FILE = "overrides.json"


class ProjectNameError(ValueError):
    pass


def projects_root() -> Path:
    env = os.environ.get(PROJECTS_ENV, "").strip()
    return Path(env) if env else REPO_ROOT / "projects"


def range_suffix(rng: TimeRange) -> str:
    return f"{RANGE_MARK}{format_seconds(rng.start_ms)}-{format_seconds(rng.end_ms)}"


def project_dir(name: str, rng: TimeRange | None = None, root: Path | None = None) -> Path:
    """Cartella del progetto. Le prove con --range finiscono in una cartella separata,
    così non toccano timeline, override e cache del progetto vero."""
    if not NAME_RE.match(name) or RANGE_MARK in name:
        raise ProjectNameError(
            f"nome progetto non valido: {name!r} (lettere, cifre, '.', '_', '-'; "
            f"niente '{RANGE_MARK}')"
        )
    folder = name + (range_suffix(rng) if rng else "")
    return (root or projects_root()) / folder
