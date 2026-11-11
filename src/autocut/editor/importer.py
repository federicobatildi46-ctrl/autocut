"""Importa un video raw dall'editor e lo porta fino al premontaggio.

Due strade (stessa cosa dopo): il file si carica dal computer (anche uno scaricato da iCloud),
oppure si sceglie fra i video già nelle cartelle Download / iCloud Drive del PC. Il file viene
copiato in `raw/<progetto>/` (l'originale non si tocca), poi parte il premontaggio:
ingest -> trascrizione (ElevenLabs Scribe, a pagamento) -> tagli delle pause.
A fine lavoro il progetto nuovo si apre riavviando l'editor (il supervisore cambia progetto).
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..ingest.step import VIDEO_EXTS
from ..paths import NAME_RE

OPEN_NEXT_FILE = ".open-next"  # in projects/: il progetto che l'editor apre al prossimo avvio
MIN_BYTES = 200_000  # sotto questa soglia di solito è un segnaposto di iCloud, non il video
MAX_BYTES = 12_000_000_000
PHASES = {
    "copy": "Copio il video nel progetto…",
    "ingest": "Riconosco il video (ingest)…",
    "transcribe": "Trascrivo il parlato con ElevenLabs Scribe (può volerci qualche minuto)…",
    "cuts": "Tolgo le pause morte (premontaggio)…",
    "done": "Premontaggio pronto",
}


class ImportError_(ValueError):
    pass


def search_roots(home: Path | None = None) -> list[Path]:
    """Dove cercare i video scaricati: Download e iCloud (Windows, macOS e Linux)."""
    h = home or Path.home()
    names = ["Downloads", "iCloudDrive", "iCloud Drive", "Pictures/iCloud Photos",
             "Pictures/iCloud Photos/Downloads", "Movies", "Videos",
             "Library/Mobile Documents/com~apple~CloudDocs"]  # fmt: skip
    return [h / n for n in names if (h / n).is_dir()]


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def candidates(roots: list[Path], limit: int = 30) -> list[dict[str, Any]]:
    """Video nelle cartelle (e nelle loro sottocartelle dirette), i più recenti per primi."""
    found: dict[Path, dict[str, Any]] = {}
    for root in roots:
        dirs = [root, *sorted(p for p in root.iterdir() if p.is_dir())][:40]
        for d in dirs:
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for p in entries:
                try:
                    if p.is_file() and is_video(p):
                        st = p.stat()
                        found[p.resolve()] = {
                            "path": str(p.resolve()), "name": p.name, "where": root.name,
                            "size_mb": round(st.st_size / 1e6, 1), "mtime": int(st.st_mtime),
                            "placeholder": st.st_size < MIN_BYTES,
                        }  # fmt: skip
                except OSError:
                    continue
    return sorted(found.values(), key=lambda c: c["mtime"], reverse=True)[:limit]


def check_source(path: Path, roots: list[Path]) -> Path:
    """Un file scelto per percorso deve stare nelle cartelle di ricerca ed essere un video."""
    p = path.resolve()
    if not any(p.is_relative_to(r.resolve()) for r in roots):
        raise ImportError_("posso importare solo dalle cartelle Download e iCloud del PC")
    if not p.is_file() or not is_video(p):
        raise ImportError_("non è un video (mov, mp4, m4v, mkv, avi, webm)")
    if p.stat().st_size < MIN_BYTES:
        raise ImportError_(
            "il file è un segnaposto di iCloud, non è ancora scaricato: aprilo in Esplora file "
            "con «Scarica sempre sul dispositivo» e riprova"
        )
    return p


def project_name_for(filename: str, projects_root: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("._-")[:40] or "video"
    if not NAME_RE.match(stem):
        stem = "video-" + stem
    name, n = stem, 2
    while (projects_root / name).exists():
        name = f"{stem}-{n}"
        n += 1
    return name


def stage_copy(src: Path, raw_root: Path, name: str, filename: str | None = None) -> Path:
    """Copia il video in raw/<progetto>/ (l'originale resta dov'è)."""
    dest = raw_root / name / (filename or src.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def default_pipeline(name: str, video: Path, phase: Callable[[str], None]) -> None:
    """Il premontaggio vero: ingest, trascrizione, tagli."""
    from ..cuts.step import run_cuts
    from ..ingest.step import run_ingest
    from ..transcribe.step import run_transcribe

    phase("ingest")
    run_ingest(name, video)
    phase("transcribe")
    run_transcribe(name)
    phase("cuts")
    run_cuts(name)


def request_open(projects_root: Path, name: str) -> None:
    projects_root.mkdir(parents=True, exist_ok=True)
    (projects_root / OPEN_NEXT_FILE).write_text(name, encoding="utf-8")


def take_open_request(projects_root: Path) -> str | None:
    """Letto (e tolto) dal supervisore: il nome del progetto da aprire al riavvio."""
    p = projects_root / OPEN_NEXT_FILE
    try:
        name = p.read_text(encoding="utf-8").strip()
        p.unlink()
    except OSError:
        return None
    return name if NAME_RE.match(name) else None


def swap_project(argv: list[str], name: str) -> list[str]:
    """argv dell'editor con un altro progetto (e senza --range, che era del vecchio)."""
    out = list(argv)
    i = out.index("editor") + 1
    out[i] = name
    for k in range(len(out) - 1, i, -1):
        if out[k] == "--range" and k + 1 < len(out):
            del out[k : k + 2]
        elif out[k].startswith("--range="):
            del out[k]
    return out
