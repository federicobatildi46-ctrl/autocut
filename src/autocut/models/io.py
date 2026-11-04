"""Lettura e scrittura deterministica dei file JSON del progetto."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel


def dumps(model: BaseModel) -> str:
    """JSON con ordine dei campi fisso, UTF-8, indentato, newline finale."""
    data = model.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def read_model[M: BaseModel](path: Path, cls: type[M]) -> M:
    return cls.model_validate_json(path.read_bytes())


def write_model(path: Path, model: BaseModel) -> None:
    """Scrittura atomica: file temporaneo nella stessa cartella, poi replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps(model).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
