"""Generazione dei JSON Schema versionati in `schemas/` (consumati dall'editor)."""

from __future__ import annotations

import json
from pathlib import Path

from .overrides import OverridesFile
from .timeline import Timeline

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"


def build_schemas() -> dict[str, str]:
    """Nome file -> contenuto (testo deterministico, newline finale)."""
    out: dict[str, str] = {}
    for name, model in (("timeline", Timeline), ("overrides", OverridesFile)):
        schema = model.model_json_schema()
        out[f"{name}.schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    return out


def write_schemas(out_dir: Path | None = None) -> list[Path]:
    target = out_dir or SCHEMAS_DIR
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in build_schemas().items():
        path = target / name
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written
