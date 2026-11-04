"""Impronta veloce di un file raw: dimensione + primo e ultimo MiB.

Leggere per intero un 4K da diversi GB a ogni rilancio sarebbe lento; questa impronta basta
a capire se il file è cambiato. Il file è aperto in sola lettura.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 20
PREFIX = "fp1:"


def fingerprint(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha256(f"autocut-fp-v1:{size}:".encode())
    with path.open("rb") as fh:
        h.update(fh.read(CHUNK))
        if size > CHUNK:
            fh.seek(max(size - CHUNK, CHUNK))
            h.update(fh.read(CHUNK))
    return PREFIX + h.hexdigest()
