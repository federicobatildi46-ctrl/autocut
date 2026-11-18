"""Brand pack: lo stile coerente di un creator o di un cliente.

Ogni brand vive in `brands/<id>/brand.json` (+ eventuali asset: loghi, font locali, reference).
Contiene palette, font, stile dei sottotitoli, lower third, grafiche, transizioni e regole del
sound. L'editor lo applica all'anteprima; Claude lo riceve quando propone o genera contenuti AI;
il render (Remotion) lo userà per grafiche, transizioni e sound.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .paths import REPO_ROOT

BRANDS_DIR = REPO_ROOT / "brands"
BRAND_FILE = "brand.json"
BRAND_SCHEMA_VERSION = 1
HEX = r"^#[0-9a-fA-F]{6}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Palette(_Model):
    background: str = Field(pattern=HEX)
    surface: str = Field(pattern=HEX)
    text: str = Field(pattern=HEX)
    muted: str = Field(pattern=HEX)
    accent: str = Field(pattern=HEX)
    accent_2: str = Field(pattern=HEX)
    highlight: str = Field(pattern=HEX)  # parola chiave nei sottotitoli


class Font(_Model):
    family: str
    source: Literal["google", "local", "system"] = "google"
    weights: list[int] = Field(default_factory=lambda: [400])
    italic: bool = False
    file: str | None = None  # per source="local", relativo alla cartella del brand
    license: str | None = None


class Emphasis(_Model):
    font: str  # chiave in fonts
    weight: int = 400
    italic: bool = False
    color: str = "highlight"  # chiave in palette
    scale: float = Field(default=1.6, ge=1, le=3)
    rule: Literal["number_or_longest", "none"] = "number_or_longest"


class CaptionStyle(_Model):
    font: str
    weight: int = 600
    case: Literal["sentence", "upper", "lower"] = "sentence"
    color: str = "text"
    size_pct: float = Field(gt=0, le=12, description="% della larghezza (verticale) o altezza")
    bottom_pct: float = Field(ge=0, le=60, description="distanza dal fondo in % dell'altezza")
    max_words: int = Field(default=4, ge=1, le=12)
    max_chars: int = Field(default=24, ge=8, le=60)
    shadow: Literal["none", "soft", "outline"] = "soft"
    emphasis: Emphasis | None = None


class Captions(_Model):
    vertical: CaptionStyle
    horizontal: CaptionStyle


class LowerThird(_Model):
    enabled: bool = True
    name: str
    role: str = ""
    show_ms: tuple[int, int] = (600, 3600)  # da / a (ms dall'inizio del montato)
    name_font: str = "sans"
    role_font: str = "sans"


class Graphics(_Model):
    style: str  # descrizione breve per Claude/Higgsfield e per Remotion
    card_radius_px: int = 28
    glass: bool = True
    glow: str = "accent"
    references: list[str] = Field(default_factory=list)  # cartelle/immagini, relative al repo


class TransitionPreset(_Model):
    id: str
    label: str
    duration_frames: int = Field(ge=0, le=60)
    sound: str | None = None  # famiglia/cue del sound design (es. "whoosh.transition")


class Transitions(_Model):
    default: str = "cut"
    presets: list[TransitionPreset]


class SoundRules(_Model):
    guide: str | None = None  # documento con le regole (relativo al repo)
    skill: str | None = None  # skill di progetto che le applica
    library: str = "library/sfx"
    levels_db: dict[str, float]
    music_under_graphics: bool = False


class BrandPack(_Model):
    schema_version: int = BRAND_SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    description: str = ""
    palette: Palette
    fonts: dict[str, Font]
    captions: Captions
    lower_third: LowerThird | None = None
    graphics: Graphics
    transitions: Transitions
    sound: SoundRules

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: int) -> int:
        if v != BRAND_SCHEMA_VERSION:
            raise ValueError(f"brand schema_version {v} non supportata")
        return v

    @model_validator(mode="after")
    def _references(self) -> BrandPack:
        colors = set(type(self.palette).model_fields)
        styles = [self.captions.vertical, self.captions.horizontal]
        for style in styles:
            if style.font not in self.fonts:
                raise ValueError(f"font {style.font!r} non definito in fonts")
            if style.color not in colors:
                raise ValueError(f"colore {style.color!r} non definito in palette")
            if style.emphasis:
                if style.emphasis.font not in self.fonts:
                    raise ValueError(f"font {style.emphasis.font!r} non definito in fonts")
                if style.emphasis.color not in colors:
                    raise ValueError(f"colore {style.emphasis.color!r} non definito in palette")
        if self.lower_third:
            for key in (self.lower_third.name_font, self.lower_third.role_font):
                if key not in self.fonts:
                    raise ValueError(f"font {key!r} non definito in fonts")
        ids = [p.id for p in self.transitions.presets]
        if len(ids) != len(set(ids)):
            raise ValueError("id delle transizioni duplicati")
        if self.transitions.default != "cut" and self.transitions.default not in ids:
            raise ValueError(f"transizione di default {self.transitions.default!r} sconosciuta")
        return self

    def google_fonts_url(self) -> str | None:
        """URL CSS di Google Fonts per tutti i font con source='google'."""
        parts = []
        for font in self.fonts.values():
            if font.source != "google":
                continue
            weights = sorted(set(font.weights)) or [400]
            if font.italic:
                axis = ";".join([f"0,{w}" for w in weights] + [f"1,{w}" for w in weights])
                parts.append(f"family={quote_plus(font.family)}:ital,wght@{axis}")
            else:
                parts.append(f"family={quote_plus(font.family)}:wght@{';'.join(map(str, weights))}")
        if not parts:
            return None
        return (
            "https://fonts.googleapis.com/css2?" + "&".join(dict.fromkeys(parts)) + "&display=swap"
        )

    def summary_for_ai(self) -> str:
        """Descrizione compatta del brand da passare a Claude nei prompt."""
        p = self.palette
        fonts = ", ".join(f"{k}: {v.family}" for k, v in self.fonts.items())
        return (
            f"Brand «{self.name}». {self.description} "
            f"Palette: sfondo {p.background}, superfici {p.surface}, testo {p.text}, "
            f"accento {p.accent} / {p.accent_2}, evidenziazione {p.highlight}. "
            f"Font: {fonts}. Stile grafico: {self.graphics.style}"
        ).strip()


class BrandError(ValueError):
    pass


def load_brand(path: Path) -> BrandPack:
    try:
        return BrandPack.model_validate_json(path.read_bytes())
    except ValueError as exc:
        raise BrandError(f"{path}: {exc}") from exc


def list_brands(root: Path | None = None) -> list[BrandPack]:
    base = root or BRANDS_DIR
    if not base.is_dir():
        return []
    out = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        file = folder / BRAND_FILE
        if file.is_file():
            brand = load_brand(file)
            if brand.id != folder.name:
                raise BrandError(f"{file}: id {brand.id!r} diverso dalla cartella {folder.name!r}")
            out.append(brand)
    return out


def brand_json(brand: BrandPack) -> str:
    return json.dumps(brand.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
