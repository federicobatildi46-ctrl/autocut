"""Preset di stile: la "grammatica" del montaggio, separata dall'identità del brand.

Il brand pack (brands/<id>/brand.json) dice CHI è il cliente: palette, font, logo, lower third.
Il preset di stile (styles/<id>/style.json) dice COME si monta: ritmo e punch-in, look del colore,
animazione e forma dei sottotitoli, hook iniziale, card grafiche, transizioni, densità dei suoni.
Si combinano liberamente: brand × stile → `resolve_look()` produce un "look" piatto, già con i
colori e i font risolti, che usano sia l'editor (anteprima) sia Remotion (render).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .brands import BrandPack, Font
from .paths import REPO_ROOT
from .sound.manifest import by_id as sfx_types

STYLES_DIR = REPO_ROOT / "styles"
STYLE_FILE = "style.json"
STYLE_SCHEMA_VERSION = 1
SOUND_EVENTS = ("caption", "emphasis", "cut", "punch", "card_in", "hook", "flash", "block")
SFX_FAMILIES = ("whooshes", "textures", "risers", "hits")
EMOJI_FONT = "Noto Color Emoji"
COLOR = r"^(#[0-9a-fA-F]{6}|[a-z_0-9]+)$"  # hex oppure chiave della palette del brand


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grade(_Model):
    """Look del colore, come filtri CSS (stessi valori nell'editor e in Remotion)."""

    contrast: float = Field(default=1.0, ge=0.5, le=1.6)
    saturation: float = Field(default=1.0, ge=0.0, le=2.0)
    brightness: float = Field(default=1.0, ge=0.6, le=1.4)
    warmth: float = Field(default=0.0, ge=0.0, le=0.4, description="quota di seppia")
    vignette: float = Field(default=0.0, ge=0.0, le=1.0)

    def css_filter(self) -> str:
        parts = [
            f"contrast({self.contrast:g})",
            f"saturate({self.saturation:g})",
            f"brightness({self.brightness:g})",
        ]
        if self.warmth:
            parts.append(f"sepia({self.warmth:g})")
        return " ".join(parts)


class PunchIn(_Model):
    enabled: bool = True
    scale: float = Field(default=1.08, ge=1.0, le=1.4)
    # phrase_alternate: cambia zoom a ogni frase, con un'ease morbida (camera fissa, premium)
    # cut_alternate: zoom secco a ogni taglio, effetto jump cut (viral)
    mode: Literal["phrase_alternate", "cut_alternate"] = "phrase_alternate"
    ease_ms: int = Field(default=400, ge=0, le=2000)


class PauseHint(_Model):
    threshold_ms: int = Field(ge=200, le=3000)
    margin_ms: int = Field(ge=0, le=500)


class Pacing(_Model):
    camera: Literal["fixed", "handheld"] = "fixed"
    target_shot_s: float = Field(default=6.0, gt=0, le=60, description="durata media inquadratura")
    punch_in: PunchIn = Field(default_factory=PunchIn)
    pauses: PauseHint | None = None  # soglie consigliate per `autocut cuts --set`


class StyleCaptions(_Model):
    font: str | None = None  # chiave in fonts dello stile; None = font del brand
    weight: int | None = None
    case: Literal["sentence", "upper", "lower"] | None = None  # None = come il brand
    size_scale: float = Field(default=1.0, ge=0.5, le=2.5)
    max_words: int | None = Field(default=None, ge=1, le=12)
    max_chars: int | None = Field(default=None, ge=8, le=60)
    bottom_pct: float | None = Field(default=None, ge=0, le=60)
    stroke_px: float = Field(default=0, ge=0, le=24, description="su una larghezza di 1080 px")
    stroke_color: str = Field(default="#000000", pattern=COLOR)
    shadow: Literal["none", "soft", "hard"] = "soft"
    colors: list[str] = Field(default_factory=list)  # ciclo per frase; vuoto = colore del brand
    emphasis: Literal["brand", "color", "none"] = "brand"
    emphasis_layout: Literal["line", "inline"] = "line"
    emphasis_scale: float | None = Field(default=None, ge=1, le=3.5)  # None = come il brand
    # tipografia della parola chiave: chiave font (dello stile o del brand), None = come il brand
    emphasis_font: str | None = None
    emphasis_weight: int | None = None
    emphasis_italic: bool | None = None
    emphasis_color: str | None = Field(default=None, pattern=COLOR)
    animation: Literal["blur_in", "pop", "none"] = "none"

    @field_validator("colors")
    @classmethod
    def _colors(cls, v: list[str]) -> list[str]:
        import re

        for c in v:
            if not re.match(COLOR, c):
                raise ValueError(f"colore {c!r} non valido")
        return v


class Hook(_Model):
    """I primi secondi = la copertina del video: testo centrato, gerarchia a 3 livelli.

    Righe del testo separate da "|": con 2 righe → [aggancio piccolo, riga GRANDE]; con 3 →
    [aggancio, GRANDE, sottotitolo]; con 1 → solo GRANDE. `*riga*` forza la riga grande.
    Mentre c'è l'hook i sottotitoli normali non compaiono.
    """

    enabled: bool = True
    duration_ms: int = Field(default=3000, ge=500, le=8000)
    center_pct: float = Field(default=52, ge=25, le=75, description="centro verticale del blocco")
    size_pct: float = Field(default=11, gt=0, le=20, description="riga grande, % della larghezza")
    kicker_ratio: float = Field(default=0.5, ge=0.2, le=1)
    sub_ratio: float = Field(default=0.4, ge=0.2, le=1)
    font: str | None = None  # aggancio e sottotitolo (chiave font dello stile o del brand)
    big_font: str | None = None  # riga grande; None = come font
    weight: int = 600
    big_weight: int = 800
    big_italic: bool = False
    case: Literal["sentence", "upper"] = "upper"
    kicker_color: str = Field(default="#FFFFFF", pattern=COLOR)
    big_color: str = Field(default="highlight", pattern=COLOR)
    sub_color: str = Field(default="#FFFFFF", pattern=COLOR)
    stroke_px: float = Field(default=0, ge=0, le=30, description="su 1080 px di larghezza")
    stroke_color: str = Field(default="#000000", pattern=COLOR)
    big_stroke_color: str | None = Field(default=None, pattern=COLOR)
    shadow: Literal["none", "soft", "hard"] = "soft"
    animation: Literal["pop", "reveal"] = "pop"
    dim: float = Field(default=0, ge=0, le=0.6, description="scurisce il video sotto l'hook")


class Cards(_Model):
    kind: Literal["liquid_glass", "sticker", "none"] = "liquid_glass"
    hold_ms: int = Field(default=2600, ge=500, le=10000)


class StyleSound(_Model):
    """Suoni dello stile. I volumi sono RELATIVI ALLA VOCE: la voce viene portata a
    `voice_lufs` (standard social ~-14 LUFS) e ogni effetto sta `relative_db` sotto
    (le guide di mix danno effetti 12-18 dB sotto il parlato: si sentono, non coprono)."""

    density: Literal["low", "medium", "high"] = "low"
    events: dict[str, str | None] = Field(default_factory=dict)
    voice_lufs: float = Field(default=-14.0, ge=-24, le=-9)
    relative_db: dict[str, float] = Field(
        default_factory=lambda: {"textures": -18, "whooshes": -16, "risers": -14, "hits": -16}
    )
    min_gap_ms: int = Field(default=800, ge=0, le=10000, description="spazio minimo tra suoni")
    # le parole chiave suonano di rado: solo un concetto ogni tanto, mai vicino a un pop-up
    emphasis_gap_ms: int = Field(default=6000, ge=0, le=60000)
    music: bool = True
    music_db: float = Field(default=-19, ge=-40, le=-6)

    @field_validator("relative_db")
    @classmethod
    def _relative(cls, v: dict[str, float]) -> dict[str, float]:
        for fam, db in v.items():
            if fam not in SFX_FAMILIES:
                raise ValueError(f"famiglia {fam!r} sconosciuta (valide: {SFX_FAMILIES})")
            if not -40 <= db <= -3:
                raise ValueError(f"{fam}: {db} dB fuori scala (-40..-3 rispetto alla voce)")
        return v

    @field_validator("events")
    @classmethod
    def _events(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        known = sfx_types()
        for key, sfx in v.items():
            if key not in SOUND_EVENTS:
                raise ValueError(f"evento sonoro {key!r} sconosciuto (validi: {SOUND_EVENTS})")
            if sfx is not None and sfx not in known:
                raise ValueError(f"suono {sfx!r} non presente nella libreria (sound/manifest.py)")
        return v


class StylePreset(_Model):
    schema_version: int = STYLE_SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    description: str = ""
    fonts: dict[str, Font] = Field(default_factory=dict)
    grade: Grade = Field(default_factory=Grade)
    pacing: Pacing = Field(default_factory=Pacing)
    captions: StyleCaptions = Field(default_factory=StyleCaptions)
    hook: Hook | None = None
    cards: Cards = Field(default_factory=Cards)
    lower_third: bool = True
    transitions: list[str] = Field(default_factory=lambda: ["cut"])
    ai_graphics: str = ""  # come chiedere a Claude/Higgsfield le grafiche in questo stile
    sound: StyleSound = Field(default_factory=StyleSound)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: int) -> int:
        if v != STYLE_SCHEMA_VERSION:
            raise ValueError(f"style schema_version {v} non supportata")
        return v

    @model_validator(mode="after")
    def _fonts(self) -> StylePreset:
        # il font dei sottotitoli, se lo stile lo cambia, deve stare nello stile; gli altri
        # riferimenti (hook, parola chiave) possono indicare anche un ruolo del brand
        # (sans / serif / display): se il brand non lo ha si usa il font dei sottotitoli.
        if self.captions.font is not None and self.captions.font not in self.fonts:
            raise ValueError(f"font {self.captions.font!r} non definito in fonts dello stile")
        return self


class StyleError(ValueError):
    pass


def load_style(path: Path) -> StylePreset:
    try:
        return StylePreset.model_validate_json(path.read_bytes())
    except ValueError as exc:
        raise StyleError(f"{path}: {exc}") from exc


def list_styles(root: Path | None = None) -> list[StylePreset]:
    base = root or STYLES_DIR
    if not base.is_dir():
        return []
    out = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        file = folder / STYLE_FILE
        if file.is_file():
            style = load_style(file)
            if style.id != folder.name:
                raise StyleError(f"{file}: id {style.id!r} diverso dalla cartella {folder.name!r}")
            out.append(style)
    return out


# --- brand × stile ---------------------------------------------------------------------


def _color(value: str, brand: BrandPack | None, fallback: str = "#FFFFFF") -> str:
    if value.startswith("#"):
        return value.upper()
    if brand is not None:
        pal = brand.palette.model_dump()
        if value in pal:
            return str(pal[value]).upper()
    return fallback


def _fonts_url(fonts: list[Font]) -> str | None:
    parts = []
    for font in fonts:
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
    return "https://fonts.googleapis.com/css2?" + "&".join(dict.fromkeys(parts)) + "&display=swap"


def resolve_look(style: StylePreset, brand: BrandPack | None, *, portrait: bool) -> dict[str, Any]:
    """Unisce stile e brand in valori concreti (hex, famiglie di font, numeri)."""
    bcap = None
    if brand is not None:
        bcap = brand.captions.vertical if portrait else brand.captions.horizontal
    c = style.captions

    def family(style_key: str | None, brand_key: str | None, default: str) -> str:
        """Prima i font dello stile, poi i ruoli del brand, poi il default."""
        for key in (style_key, brand_key):
            if key is None:
                continue
            if key in style.fonts:
                return style.fonts[key].family
            if brand is not None and key in brand.fonts:
                return brand.fonts[key].family
        return default

    cap_font = family(c.font, bcap.font if bcap else None, "Inter")
    base_color = _color(bcap.color, brand) if bcap else "#FFFFFF"
    colors = [_color(x, brand) for x in c.colors] or [base_color]
    emphasis = None
    if c.emphasis == "brand" and bcap and bcap.emphasis and bcap.emphasis.rule != "none":
        e = bcap.emphasis
        emphasis = {
            "font": family(c.emphasis_font, e.font, "Georgia"),
            "weight": c.emphasis_weight or e.weight,
            "italic": e.italic if c.emphasis_italic is None else c.emphasis_italic,
            "color": _color(c.emphasis_color or e.color, brand),
            "scale": c.emphasis_scale or e.scale,
            "layout": c.emphasis_layout,
        }
    elif c.emphasis == "color":
        emphasis = {
            "font": family(c.emphasis_font, None, cap_font),
            "weight": c.emphasis_weight,
            "italic": bool(c.emphasis_italic),
            "color": _color(c.emphasis_color or "highlight", brand, "#FFD60A"),
            "scale": c.emphasis_scale or 1.0,
            "layout": c.emphasis_layout,
        }

    hook = None
    if style.hook and style.hook.enabled:
        h = style.hook
        small = family(h.font, None, cap_font)
        hook = {
            "duration_ms": h.duration_ms,
            "center_pct": h.center_pct,
            "size_pct": h.size_pct,
            "kicker_ratio": h.kicker_ratio,
            "sub_ratio": h.sub_ratio,
            "font": small,
            "big_font": family(h.big_font, None, small),
            "weight": h.weight,
            "big_weight": h.big_weight,
            "big_italic": h.big_italic,
            "case": h.case,
            "colors": {
                "kicker": _color(h.kicker_color, brand),
                "big": _color(h.big_color, brand, "#FFD60A"),
                "sub": _color(h.sub_color, brand),
            },
            "stroke_px": h.stroke_px,
            "stroke_color": _color(h.stroke_color, brand, "#000000"),
            "big_stroke_color": _color(h.big_stroke_color or h.stroke_color, brand, "#000000"),
            "shadow": h.shadow,
            "animation": h.animation,
            "dim": h.dim,
        }

    fonts = list(style.fonts.values()) + (list(brand.fonts.values()) if brand else [])
    # emoji uguali su ogni computer (anche le bandiere, che Windows non disegna)
    fonts.append(Font(family=EMOJI_FONT, source="google", weights=[400], license="OFL"))
    pal = brand.palette if brand else None
    lower_third = None
    if style.lower_third and brand and brand.lower_third and brand.lower_third.enabled:
        lt = brand.lower_third
        lower_third = {
            "name": lt.name,
            "role": lt.role,
            "show_ms": list(lt.show_ms),
            "name_font": family(None, lt.name_font, "Inter"),
            "role_font": family(None, lt.role_font, "Inter"),
        }

    return {
        "style": style.id,
        "style_name": style.name,
        "brand": brand.id if brand else None,
        "fonts_url": _fonts_url(fonts),
        "grade": {**style.grade.model_dump(), "css_filter": style.grade.css_filter()},
        "pacing": style.pacing.model_dump(mode="json"),
        "captions": {
            "font": cap_font,
            "weight": c.weight or (bcap.weight if bcap else 700),
            "case": c.case or (bcap.case if bcap else "sentence"),
            "size_pct": round((bcap.size_pct if bcap else 5.0) * c.size_scale, 2),
            "bottom_pct": c.bottom_pct
            if c.bottom_pct is not None
            else (bcap.bottom_pct if bcap else 36),
            "max_words": c.max_words or (bcap.max_words if bcap else 4),
            "max_chars": c.max_chars or (bcap.max_chars if bcap else 24),
            "stroke_px": c.stroke_px,
            "stroke_color": _color(c.stroke_color, brand, "#000000"),
            "shadow": c.shadow,
            "colors": colors,
            "emphasis": emphasis,
            "animation": c.animation,
        },
        "hook": hook,
        "cards": {
            **style.cards.model_dump(),
            "accent": _color("accent", brand, "#2F6BFF"),
            "surface": pal.surface if pal else "#0E1430",
            "title_font": emphasis["font"]
            if emphasis and emphasis["font"]
            else family(c.font, bcap.font if bcap else None, "Inter"),
        },
        "lower_third": lower_third,
        "transitions": style.transitions,
        "ai_graphics": style.ai_graphics,
        "sound": style.sound.model_dump(mode="json"),
    }


def style_json(style: StylePreset) -> str:
    return json.dumps(style.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
