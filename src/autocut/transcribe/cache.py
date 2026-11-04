"""Cache delle trascrizioni in projects/<nome>/transcript/.

La chiave dipende dall'impronta del file camera, dal tratto, dai parametri di estrazione e
dalla richiesta a Scribe: se nulla di questo cambia, la trascrizione non si ripaga.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..models.timeline import TimeRange

TRANSCRIPT_DIR = "transcript"


def cache_key(
    *,
    fingerprint: str,
    rng: TimeRange | None,
    extract_params: dict[str, Any],
    request_params: dict[str, Any],
) -> str:
    payload = {
        "v": 1,
        "camera": fingerprint,
        "range": rng.model_dump(mode="json") if rng else None,
        "extract": extract_params,
        "request": request_params,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def short(key: str) -> str:
    return key.split(":", 1)[-1][:16]


def cache_path(project_dir: Path, key: str) -> Path:
    return project_dir / TRANSCRIPT_DIR / f"scribe-{short(key)}.json"


def load(path: Path, key: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("cache_key") != key:
        return None
    return data["response"]


def store(path: Path, key: str, request_params: dict[str, Any], response: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"cache_key": key, "request": request_params, "response": response}
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
