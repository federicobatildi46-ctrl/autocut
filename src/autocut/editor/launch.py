"""Avvio dell'editor locale: prepara i media di anteprima e serve l'interfaccia su 127.0.0.1."""

from __future__ import annotations

import socket
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from ..ingest.fingerprint import fingerprint
from ..models.io import read_model
from ..models.timeline import Timeline
from ..paths import TIMELINE_FILE, project_dir
from ..timeparse import parse_range
from .media import prepare
from .server import create_app


class EditorError(ValueError):
    pass


def build(
    name: str,
    *,
    range_text: str | None = None,
    projects_root: Path | None = None,
    log: Callable[[str], None] = lambda s: None,
):
    pdir = project_dir(name, parse_range(range_text) if range_text else None, projects_root)
    tl_path = pdir / TIMELINE_FILE
    if not tl_path.exists():
        raise EditorError(f"nessuna timeline in {pdir}: lancia prima ingest, transcribe e cuts")
    tl = read_model(tl_path, Timeline)
    if not tl.segments:
        raise EditorError("la timeline non ha ancora segmenti: lancia prima transcribe e cuts")
    cam = tl.sources.camera
    src = Path(cam.path_hint) if cam.path_hint else None
    if src is None or not src.is_file():
        raise EditorError(f"file camera non trovato: {cam.path_hint} (rilancia ingest)")
    if fingerprint(src) != cam.fingerprint:
        raise EditorError(f"{cam.file_name} è cambiato dall'ingest: rilancia ingest")
    media = prepare(pdir, tl, src, log=log)
    return create_app(pdir, media, auto_popups=True, keepalive=True), pdir


def port_busy(port: int) -> bool:
    """True se su 127.0.0.1:port c'è già qualcosa in ascolto (es. un editor vecchio acceso)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def serve(app, *, port: int, open_browser: bool) -> None:
    import uvicorn

    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
