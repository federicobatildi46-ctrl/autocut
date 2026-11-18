"""Pannello Filtri: il look del colore del video, sopra quello dello stile.

Preset (Vivido, Caldo, Freddo, Cinema, Pastello, Bianco e nero) e cursori per luminosità,
contrasto, saturazione, calore e vignetta. Per stile, in projects/<nome>/filters.json. Cambia
look["grade"], quindi vale uguale nell'anteprima, nel render e nella copertina Viral.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .styles import Grade

FILTERS_FILE = "filters.json"
FIELDS = ("brightness", "contrast", "saturation", "warmth", "vignette", "hue", "grayscale")

PRESETS: list[dict[str, Any]] = [
    {"id": "style", "label": "Originale dello stile", "values": {}},
    {"id": "natural", "label": "Naturale", "values": {"contrast": 1.0, "saturation": 1.0, "brightness": 1.0, "warmth": 0.0, "vignette": 0.0, "hue": 0.0, "grayscale": 0.0}},
    {"id": "vivid", "label": "Vivido", "values": {"contrast": 1.1, "saturation": 1.45, "brightness": 1.05, "warmth": 0.03, "vignette": 0.0, "hue": 0.0, "grayscale": 0.0}},
    {"id": "warm", "label": "Caldo", "values": {"contrast": 1.05, "saturation": 1.15, "brightness": 1.04, "warmth": 0.18, "vignette": 0.1, "hue": 0.0, "grayscale": 0.0}},
    {"id": "cool", "label": "Freddo", "values": {"contrast": 1.06, "saturation": 1.05, "brightness": 1.02, "warmth": 0.0, "vignette": 0.1, "hue": -10.0, "grayscale": 0.0}},
    {"id": "cinema", "label": "Cinema", "values": {"contrast": 1.15, "saturation": 0.85, "brightness": 0.97, "warmth": 0.08, "vignette": 0.35, "hue": 0.0, "grayscale": 0.0}},
    {"id": "pastel", "label": "Pastello", "values": {"contrast": 0.9, "saturation": 0.8, "brightness": 1.08, "warmth": 0.05, "vignette": 0.0, "hue": 0.0, "grayscale": 0.0}},
    {"id": "bw", "label": "Bianco e nero", "values": {"contrast": 1.15, "saturation": 1.0, "brightness": 1.02, "warmth": 0.0, "vignette": 0.25, "hue": 0.0, "grayscale": 1.0}},
]  # fmt: skip
PRESET_IDS = {p["id"] for p in PRESETS}


class StyleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = "style"
    values: dict[str, float] = Field(default_factory=dict)  # ritocchi sopra il preset


class FiltersFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    styles: dict[str, StyleFilters] = Field(default_factory=dict)


class FilterError(ValueError):
    pass


def load(project_dir: Path) -> FiltersFile:
    p = project_dir / FILTERS_FILE
    if not p.exists():
        return FiltersFile()
    return FiltersFile.model_validate_json(p.read_bytes())


def save(project_dir: Path, data: FiltersFile) -> None:
    p = project_dir / FILTERS_FILE
    tmp = p.with_suffix(".partial")
    tmp.write_text(json.dumps(data.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def for_style(data: FiltersFile, style: str | None) -> StyleFilters:
    return data.styles.get(style or "", StyleFilters())


def update(
    data: FiltersFile,
    style: str | None,
    *,
    preset: str | None = None,
    values: dict[str, Any] | None = None,
    reset: bool = False,
) -> FiltersFile:
    sf = StyleFilters() if reset else for_style(data, style)
    if preset is not None:
        if preset not in PRESET_IDS:
            raise FilterError(f"filtro {preset!r} sconosciuto")
        sf = StyleFilters(preset=preset)  # un preset nuovo riparte dai suoi valori
    if values:
        bad = set(values) - set(FIELDS)
        if bad:
            raise FilterError(f"campi sconosciuti: {sorted(bad)}")
        merged = {**sf.values, **{k: float(v) for k, v in values.items()}}
        try:
            Grade(**merged)  # controlla i limiti
        except ValidationError as exc:
            raise FilterError(exc.errors()[0]["msg"]) from exc
        sf = sf.model_copy(update={"values": merged})
    return data.model_copy(update={"styles": {**data.styles, style or "": sf}})


def apply_to_look(look: dict[str, Any], sf: StyleFilters) -> dict[str, Any]:
    """Look con il colore del pannello Filtri (stile → preset → ritocchi)."""
    base = {k: v for k, v in look["grade"].items() if k in Grade.model_fields}
    preset = next((p["values"] for p in PRESETS if p["id"] == sf.preset), {})
    g = Grade(**{**base, **preset, **sf.values})
    return {**look, "grade": {**g.model_dump(), "css_filter": g.css_filter()}}
