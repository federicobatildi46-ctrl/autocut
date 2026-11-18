"""Testo personalizzato dei sottotitoli (pannello Testo dell'editor).

Le scelte stanno in projects/<nome>/text_style.json, separate per preset di stile:
- ``base``: vale per tutti i sottotitoli (font, colori, stile, posizione, rotazione, grandezza);
- ``scenes``: modifiche di una sola scena (frase), con la chiave = id della prima parola;
  possono cambiare il testo e qualsiasi campo di ``base``.

L'anteprima dell'editor e il render Remotion leggono lo stesso file, così il risultato
esportato è quello che vedi. Solo font del catalogo (Google Fonts, licenza OFL).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .brands import Font
from .styles import _fonts_url

TEXT_FILE = "text_style.json"
NO_STYLE = "_none"

# Font scelti per i due preset. Pesi = solo quelli che esistono davvero su Google Fonts
# (un peso inesistente fa fallire tutto il CSS).
_V = "viral"
_P = "premium"


def _font(family: str, weights: list[int], italic: bool, kind: str, group: str) -> dict[str, Any]:
    return {"family": family, "weights": weights, "italic": italic, "kind": kind, "set": group}


CATALOG: list[dict[str, Any]] = [
    # Viral / provinciale: bastoni grossi, display, cartoon
    _font("Anton", [400], False, "sans", _V),
    _font("Bebas Neue", [400], False, "sans", _V),
    _font("Montserrat", [500, 700, 900], True, "sans", _V),
    _font("Poppins", [500, 700, 800], True, "sans", _V),
    _font("Lilita One", [400], False, "display", _V),
    _font("Bangers", [400], False, "display", _V),
    _font("Luckiest Guy", [400], False, "display", _V),
    _font("Archivo Black", [400], False, "sans", _V),
    _font("Titan One", [400], False, "display", _V),
    _font("Rubik", [500, 700, 900], True, "sans", _V),
    _font("Passion One", [400, 700, 900], False, "display", _V),
    _font("Oswald", [500, 700], False, "sans", _V),
    _font("Kanit", [500, 700, 900], True, "sans", _V),
    _font("Fredoka", [500, 700], False, "display", _V),
    # Premium / tech: serif editoriali per la parola chiave + sans puliti
    _font("Playfair Display", [500, 700, 900], True, "serif", _P),
    _font("Instrument Serif", [400], True, "serif", _P),
    _font("DM Serif Display", [400], True, "serif", _P),
    _font("Cormorant Garamond", [500, 700], True, "serif", _P),
    _font("Fraunces", [500, 700, 900], True, "serif", _P),
    _font("Bodoni Moda", [500, 700, 900], True, "serif", _P),
    _font("Inter", [500, 700, 800], False, "sans", _P),
    _font("Manrope", [500, 700, 800], False, "sans", _P),
    _font("Space Grotesk", [500, 700], False, "sans", _P),
    _font("Sora", [500, 700, 800], False, "sans", _P),
    _font("Syne", [500, 700, 800], False, "sans", _P),
    _font("Plus Jakarta Sans", [500, 700, 800], True, "sans", _P),
    _font("Outfit", [500, 700, 900], False, "sans", _P),
    _font("Unbounded", [500, 700, 900], False, "display", _P),
]
BY_FAMILY = {f["family"]: f for f in CATALOG}

# Stili del testo (come i preset di CapCut)
PRESETS = ("stroke", "shadow", "hard", "glow", "box", "plain")


class CaptionStyle(BaseModel):
    """Campi opzionali: None = usa il valore del preset di stile."""

    model_config = ConfigDict(extra="forbid")

    font: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    case: Literal["sentence", "upper", "lower"] | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    emph_font: str | None = None
    emph_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    emph_italic: bool | None = None
    preset: Literal["stroke", "shadow", "hard", "glow", "box", "plain"] | None = None
    # colore del contorno, del box o dell'alone
    fx_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    x_pct: float | None = Field(default=None, ge=-60, le=60)  # spostamento in % della larghezza
    y_pct: float | None = Field(default=None, ge=-80, le=80)  # spostamento in % dell'altezza
    scale: float | None = Field(default=None, ge=0.3, le=3.0)
    rotation: float | None = Field(default=None, ge=-180, le=180)


class SceneEdit(CaptionStyle):
    text: str | None = Field(default=None, max_length=200)


class StyleText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: CaptionStyle = CaptionStyle()
    scenes: dict[str, SceneEdit] = {}


class TextStyleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    styles: dict[str, StyleText] = {}


class TextStyleError(ValueError):
    pass


def load(project_dir: Path) -> TextStyleFile:
    path = project_dir / TEXT_FILE
    if not path.exists():
        return TextStyleFile()
    return TextStyleFile.model_validate_json(path.read_text(encoding="utf-8"))


def save(project_dir: Path, data: TextStyleFile) -> None:
    path = project_dir / TEXT_FILE
    tmp = path.with_suffix(".partial")
    body = data.model_dump(mode="json", exclude_none=True)
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def for_style(data: TextStyleFile, style_id: str | None) -> StyleText:
    return data.styles.get(style_id or NO_STYLE) or StyleText()


def allowed_fonts(look: dict[str, Any] | None) -> set[str]:
    fams = set(BY_FAMILY)
    if look:
        cap = look["captions"]
        fams.add(cap["font"])
        if cap.get("emphasis") and cap["emphasis"].get("font"):
            fams.add(cap["emphasis"]["font"])
    return fams


def update(
    data: TextStyleFile,
    style_id: str | None,
    *,
    scene: str | None,
    fields: dict[str, Any],
    reset: bool = False,
    allowed: set[str],
) -> TextStyleFile:
    """Applica una modifica (``None`` in un campo = torna al valore dello stile)."""
    key = style_id or NO_STYLE
    st = data.styles.get(key) or StyleText()
    for fam_key in ("font", "emph_font"):
        fam = fields.get(fam_key)
        if fam is not None and fam not in allowed:
            raise TextStyleError(f"font {fam!r} non disponibile")
    if scene is None:
        current = {} if reset else st.base.model_dump(exclude_none=True)
        st.base = CaptionStyle.model_validate({**current, **fields})
    else:
        if not scene.strip():
            raise TextStyleError("scena senza id")
        current = {} if reset else st.scenes.get(scene, SceneEdit()).model_dump(exclude_none=True)
        merged = SceneEdit.model_validate({**current, **fields})
        if merged.text is not None and not merged.text.strip():
            merged.text = None
        scenes = dict(st.scenes)
        if merged.model_dump(exclude_none=True):
            scenes[scene] = merged
        else:
            scenes.pop(scene, None)
        st.scenes = scenes
    styles = dict(data.styles)
    styles[key] = st
    return TextStyleFile(version=data.version, styles=styles)


def _weights(family: str, bold: bool) -> int:
    f = BY_FAMILY.get(family)
    if f is None:
        return 800 if bold else 500
    ws = f["weights"]
    return max(ws) if bold else min(ws)


def caption_fields(base: dict[str, Any], st: CaptionStyle) -> dict[str, Any]:
    """Campi ``look.captions`` risultanti (per tutti i sottotitoli o una scena)."""
    cap = dict(base)
    cap.setdefault("italic", False)
    cap.setdefault("effect", "none")
    cap.setdefault("fx_color", cap.get("stroke_color", "#000000"))
    cap.setdefault("x_pct", 0.0)
    cap.setdefault("y_pct", 0.0)
    cap.setdefault("scale", 1.0)
    cap.setdefault("rotation", 0.0)
    if st.font:
        cap["font"] = st.font
        if st.bold is None:
            cap["weight"] = _weights(st.font, cap["weight"] >= 700)
    if st.bold is not None:
        cap["weight"] = _weights(cap["font"], st.bold)
    if st.italic is not None:
        cap["italic"] = st.italic
    if st.case:
        cap["case"] = st.case
    if st.color:
        cap["colors"] = [st.color.upper()]
    if st.fx_color:
        cap["fx_color"] = st.fx_color.upper()
        cap["stroke_color"] = st.fx_color.upper()
    if st.preset:
        stroke = cap.get("stroke_px") or 0
        cap["effect"] = "none"
        if st.preset == "stroke":
            cap["stroke_px"] = stroke if stroke >= 4 else 6
            cap["shadow"] = "hard"
        elif st.preset in ("shadow", "hard", "plain"):
            cap["stroke_px"] = 0
            cap["shadow"] = {"shadow": "soft", "hard": "hard", "plain": "none"}[st.preset]
        else:  # glow | box
            cap["stroke_px"] = 0
            cap["shadow"] = "none"
            cap["effect"] = st.preset
            if st.fx_color is None and st.preset == "glow":
                emph = cap.get("emphasis")
                cap["fx_color"] = (emph or {}).get("color") or "#FFD60A"
    if any(v is not None for v in (st.emph_font, st.emph_color, st.emph_italic)):
        emph = dict(
            cap.get("emphasis")
            or {
                "font": None,
                "weight": None,
                "italic": False,
                "color": cap["colors"][0],
                "scale": 1.0,
                "layout": "inline",
            }
        )
        if st.emph_font:
            emph["font"] = st.emph_font
            emph["weight"] = _weights(st.emph_font, True)
        if st.emph_color:
            emph["color"] = st.emph_color.upper()
        if st.emph_italic is not None:
            emph["italic"] = st.emph_italic
        cap["emphasis"] = emph
    for k in ("x_pct", "y_pct", "scale", "rotation"):
        v = getattr(st, k)
        if v is not None:
            cap[k] = v
    return cap


def _font_objs(families: set[str]) -> list[Font]:
    out = []
    for fam in sorted(families):
        f = BY_FAMILY.get(fam)
        if f:
            out.append(Font(family=fam, source="google", weights=f["weights"],
                            italic=f["italic"], license="OFL"))  # fmt: skip
    return out


def apply_to_look(look: dict[str, Any], st: StyleText) -> dict[str, Any]:
    """Look con il testo di ``base`` applicato e i font delle scelte già nel CSS."""
    out = copy.deepcopy(look)
    out["captions"] = caption_fields(out["captions"], st.base)
    fams = {out["captions"]["font"]}
    if out["captions"].get("emphasis") and out["captions"]["emphasis"].get("font"):
        fams.add(out["captions"]["emphasis"]["font"])
    for sc in st.scenes.values():
        fams.update(x for x in (sc.font, sc.emph_font) if x)
    extra = _fonts_url(_font_objs(fams))
    if extra:
        out["fonts_url"] = _merge_urls(out.get("fonts_url"), extra)
    return out


def scene_overrides(look_captions: dict[str, Any], edit: SceneEdit) -> dict[str, Any]:
    """Solo i campi che la scena cambia rispetto a ``look_captions`` (per il render)."""
    full = caption_fields(look_captions, edit)
    return {k: v for k, v in full.items() if look_captions.get(k) != v}


def _merge_urls(a: str | None, b: str) -> str:
    if not a:
        return b
    parts = [p for p in (a.split("?", 1)[1] + "&" + b.split("?", 1)[1]).split("&") if p]
    keep = list(dict.fromkeys(p for p in parts if p != "display=swap"))
    return "https://fonts.googleapis.com/css2?" + "&".join(keep) + "&display=swap"


def catalog_payload(style_id: str | None) -> dict[str, Any]:
    """Font da mostrare nel pannello: quelli del preset attivo (tutti senza preset)."""
    fonts = [f for f in CATALOG if style_id is None or f["set"] == style_id] or CATALOG
    return {
        "fonts": fonts,
        "fonts_url": _fonts_url(_font_objs({f["family"] for f in fonts})),
        "presets": list(PRESETS),
    }
