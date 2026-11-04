"""Estrazione dell'audio della camera per la trascrizione (il raw è solo letto)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..models.timeline import TimeRange

# Parametri che entrano nella chiave della cache: se cambiano, la trascrizione va rifatta.
EXTRACT_PARAMS = {
    "map": "0:a:0",  # prima traccia audio (l'AAC dell'iPhone; la APAC spaziale viene dopo)
    "channels": 1,
    "sample_rate": 16000,
    "codec": "flac",
}


class AudioExtractError(RuntimeError):
    pass


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def extract_audio(src: Path, dest: Path, *, rng: TimeRange | None = None) -> Path:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise AudioExtractError("ffmpeg non trovato nel PATH")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".partial" + dest.suffix)

    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if rng is not None:
        cmd += ["-ss", _seconds(rng.start_ms), "-to", _seconds(rng.end_ms)]
    cmd += [
        "-i", str(src),
        "-map", EXTRACT_PARAMS["map"],
        "-vn",
        "-ac", str(EXTRACT_PARAMS["channels"]),
        "-ar", str(EXTRACT_PARAMS["sample_rate"]),
        "-c:a", EXTRACT_PARAMS["codec"],
        "-bitexact",
        str(tmp),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        msg = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise AudioExtractError(f"estrazione audio da {src.name}: {msg}")
    os.replace(tmp, dest)
    return dest
