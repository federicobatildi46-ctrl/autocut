"""Effetti: animazioni di testo e sticker (entrata / uscita / loop) e transizioni tra clip.

Le scelte stanno in projects/<nome>/effects.json, separate per preset di stile. Ogni stile ha
la sua galleria (Premium morbida ed elegante, Viral d'impatto) e i suoi valori di partenza;
Claude può comporre il preset guardando il parlato, i tagli e i cambi di scena.

Le animazioni vere stanno in motion/src/anim.js (stesso codice per editor e render);
qui ci sono solo il catalogo, la validazione, i default e i "punti di transizione".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models.timeline import Timeline
from .overrides.resolve import EffectiveRange

EFFECTS_FILE = "effects.json"
Phase = Literal["in", "out", "loop"]
V, P = "viral", "premium"


def _a(id_: str, label: str, phase: str, sets: tuple[str, ...], text_only: bool = False) -> dict:
    return {"id": id_, "label": label, "phase": phase, "sets": list(sets), "text_only": text_only}


# Galleria animazioni (stessi id di motion/src/anim.js)
ANIMS: list[dict[str, Any]] = [
    _a("none", "Nessuna", "in", (V, P)),
    _a("fade", "Dissolvenza", "in", (V, P)),
    _a("rise", "Emersione", "in", (P,)),
    _a("blur_in", "Messa a fuoco", "in", (P,)),
    _a("wipe_in", "Rivelazione", "in", (P,)),
    _a("words_blur", "Parola per parola", "in", (P,), text_only=True),
    _a("slide_up", "Sale dal basso", "in", (V, P)),
    _a("slide_down", "Scende dall'alto", "in", (V, P)),
    _a("slide_left", "Entra da destra", "in", (V, P)),
    _a("slide_right", "Entra da sinistra", "in", (V, P)),
    _a("zoom_in", "Zoom", "in", (V, P)),
    _a("glow_in", "Bagliore", "in", (V, P)),
    _a("typewriter", "Macchina da scrivere", "in", (V, P), text_only=True),
    _a("pop", "Pop", "in", (V,)),
    _a("words_pop", "Pop parola per parola", "in", (V,), text_only=True),
    _a("bounce", "Rimbalzo", "in", (V,)),
    _a("drop", "Cade", "in", (V,)),
    _a("zoom_big", "Da gigante", "in", (V,)),
    _a("spin_in", "Giro", "in", (V,)),
    _a("stretch", "Elastico", "in", (V,)),
    _a("none", "Nessuna", "out", (V, P)),
    _a("fade", "Dissolvenza", "out", (V, P)),
    _a("sink", "Scende e sfuma", "out", (P,)),
    _a("blur_out", "Sfuoca", "out", (P, V)),
    _a("wipe_out", "Cancella", "out", (P,)),
    _a("slide_up", "Esce in alto", "out", (V, P)),
    _a("slide_down", "Esce in basso", "out", (V, P)),
    _a("slide_left", "Esce a sinistra", "out", (V, P)),
    _a("slide_right", "Esce a destra", "out", (V, P)),
    _a("zoom_out", "Rimpicciolisce", "out", (V, P)),
    _a("pop_out", "Scoppia", "out", (V,)),
    _a("glow_out", "Lampo", "out", (V,)),
    _a("spin_out", "Gira via", "out", (V,)),
    _a("none", "Nessuno", "loop", (V, P)),
    _a("float", "Galleggia", "loop", (V, P)),
    _a("pulse", "Pulsa", "loop", (V, P)),
    _a("glow", "Bagliore", "loop", (V, P)),
    _a("heartbeat", "Battito", "loop", (V,)),
    _a("wiggle", "Dondola", "loop", (V,)),
    _a("shake", "Trema", "loop", (V,)),
    _a("spin", "Ruota", "loop", (V,)),
]

# Transizioni tra clip: ufficiali @remotion/transitions (CSS) + alcune in stile CapCut
TRANSITIONS: list[dict[str, Any]] = [
    {"id": "none", "label": "Taglio netto", "sets": [V, P], "source": "-"},
    {"id": "fade", "label": "Dissolvenza", "sets": [V, P], "source": "remotion"},
    {"id": "dip_black", "label": "Passaggio al nero", "sets": [P], "source": "autocut"},
    {"id": "blur", "label": "Dissolvenza sfocata", "sets": [P], "source": "autocut"},
    {"id": "wipe_left", "label": "Tendina", "sets": [P, V], "source": "remotion"},
    {"id": "iris", "label": "Iride", "sets": [P], "source": "remotion"},
    {"id": "clock_wipe", "label": "Orologio", "sets": [P], "source": "remotion"},
    {"id": "slide_left", "label": "Scorri a sinistra", "sets": [P, V], "source": "remotion"},
    {"id": "slide_up", "label": "Scorri in alto", "sets": [P, V], "source": "remotion"},
    {"id": "cube", "label": "Cubo 3D", "sets": [P, V], "source": "remotion"},
    {"id": "flip", "label": "Ribalta", "sets": [V], "source": "remotion"},
    {"id": "push_cut", "label": "Spinta con flash", "sets": [V], "source": "remotion"},
    {"id": "zoom", "label": "Zoom", "sets": [V], "source": "autocut"},
    {"id": "whip", "label": "Whip (frusta)", "sets": [V], "source": "autocut"},
    {"id": "flash", "label": "Flash bianco", "sets": [V], "source": "autocut"},
]
TRANSITION_IDS = {t["id"] for t in TRANSITIONS}

DEFAULTS: dict[str, dict[str, Any]] = {
    V: {
        "captions": {"in": {"type": "pop", "ms": 280}, "out": {"type": "none", "ms": 200}},
        "sticker_default": {
            "in": {"type": "pop", "ms": 360},
            "out": {"type": "zoom_out", "ms": 220},
            "loop": {"type": "none", "ms": 0, "speed": 1.0},
        },
        "transition_scene": {"type": "whip", "ms": 300},  # cambio di inquadratura
        "transition_block": {"type": "zoom", "ms": 260},  # nuovo blocco dopo una pausa lunga
    },
    P: {
        "captions": {"in": {"type": "words_blur", "ms": 380}, "out": {"type": "fade", "ms": 250}},
        "sticker_default": {
            "in": {"type": "rise", "ms": 650},
            "out": {"type": "fade", "ms": 420},
            "loop": {"type": "none", "ms": 0, "speed": 1.0},
        },
        "transition_scene": {"type": "blur", "ms": 520},
        "transition_block": {"type": "none", "ms": 400},
    },
}


class Anim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    ms: int = Field(default=300, ge=0, le=3000)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class ItemAnims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_: Anim | None = Field(default=None, alias="in")
    out: Anim | None = None
    loop: Anim | None = None


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    ms: int = Field(default=300, ge=100, le=1500)
    origin: Literal["auto", "ai", "user"] = "user"


class StyleEffects(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    captions: ItemAnims = ItemAnims()
    sticker_default: ItemAnims = ItemAnims()
    stickers: dict[str, ItemAnims] = {}
    transitions: dict[str, Transition] = {}
    suggested: bool = False
    note: str = ""


class EffectsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    styles: dict[str, StyleEffects] = {}


class EffectsError(ValueError):
    pass


def load(project_dir: Path) -> EffectsFile:
    path = project_dir / EFFECTS_FILE
    if not path.exists():
        return EffectsFile()
    return EffectsFile.model_validate_json(path.read_text(encoding="utf-8"))


def save(project_dir: Path, data: EffectsFile) -> None:
    path = project_dir / EFFECTS_FILE
    tmp = path.with_suffix(".partial")
    body = data.model_dump(mode="json", by_alias=True, exclude_none=True)
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _key(style_id: str | None) -> str:
    return style_id if style_id in DEFAULTS else V


def for_style(data: EffectsFile, style_id: str | None) -> StyleEffects:
    return data.styles.get(style_id or "_none") or StyleEffects()


def anim_ids(phase: str, text: bool) -> set[str]:
    return {a["id"] for a in ANIMS if a["phase"] == phase and (text or not a["text_only"])}


def _check(phase: str, spec: dict[str, Any] | None, text: bool) -> dict[str, Any] | None:
    if spec is None:
        return None
    a = Anim.model_validate(spec)
    if a.type not in anim_ids(phase, text):
        raise EffectsError(f"effetto {a.type!r} non valido per {phase}")
    return a.model_dump()


def _merge(base: dict[str, Any], over: ItemAnims | None) -> dict[str, Any]:
    out = {k: dict(v) for k, v in base.items()}
    if over is not None:
        for phase, val in (("in", over.in_), ("out", over.out), ("loop", over.loop)):
            if val is not None:
                out[phase] = val.model_dump()
    return out


def resolved(style_id: str | None, st: StyleEffects) -> dict[str, Any]:
    """Valori effettivi: default dello stile + scelte salvate."""
    d = DEFAULTS[_key(style_id)]
    sticker_default = _merge(d["sticker_default"], st.sticker_default)
    return {
        "captions": _merge(d["captions"], st.captions),
        "sticker_default": sticker_default,
        "stickers": {k: _merge(sticker_default, v) for k, v in st.stickers.items()},
        "transitions": {k: v.model_dump() for k, v in st.transitions.items()},
        "transition_scene": dict(d["transition_scene"]),
        "transition_block": dict(d["transition_block"]),
        "suggested": st.suggested,
        "note": st.note,
    }


def sticker_anim(res: dict[str, Any], popup_id: str) -> dict[str, Any]:
    return res["stickers"].get(popup_id) or res["sticker_default"]


def transition_for(res: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    """Transizione di un punto: scelta salvata, altrimenti il default dello stile."""
    t = res["transitions"].get(b["id"])
    if t is None:
        t = res["transition_scene"] if b["kind"] == "scene" else (
            res["transition_block"] if b.get("block") else None)  # fmt: skip
    if not t or t["type"] == "none":
        return None
    return t


def update(
    data: EffectsFile,
    style_id: str | None,
    *,
    target: str,
    item: str | None = None,
    phase: str | None = None,
    spec: dict[str, Any] | None = None,
) -> EffectsFile:
    """target: captions | sticker_default | sticker (item = id pop-up) | transition (item = punto).
    spec None = torna al valore dello stile."""
    key = style_id or "_none"
    st = (data.styles.get(key) or StyleEffects()).model_copy(deep=True)
    if target == "transition":
        if not item:
            raise EffectsError("transizione senza punto")
        trans = dict(st.transitions)
        if spec is None:
            trans.pop(item, None)
        else:
            t = Transition.model_validate({"origin": "user", **spec})
            if t.type not in TRANSITION_IDS:
                raise EffectsError(f"transizione {t.type!r} sconosciuta")
            trans[item] = t
        st.transitions = trans
    else:
        if phase not in ("in", "out", "loop"):
            raise EffectsError("fase non valida (in, out, loop)")
        text = target == "captions"
        if text and phase == "loop":
            raise EffectsError("il loop vale solo per gli sticker")
        val = _check(phase, spec, text)
        if target == "captions":
            st.captions = _set(st.captions, phase, val)
        elif target == "sticker_default":
            st.sticker_default = _set(st.sticker_default, phase, val)
        elif target == "sticker":
            if not item:
                raise EffectsError("sticker senza id")
            stickers = dict(st.stickers)
            stickers[item] = _set(stickers.get(item) or ItemAnims(), phase, val)
            st.stickers = stickers
        else:
            raise EffectsError(f"obiettivo {target!r} sconosciuto")
    styles = dict(data.styles)
    styles[key] = st
    return EffectsFile(version=data.version, styles=styles)


def _set(items: ItemAnims, phase: str, val: dict[str, Any] | None) -> ItemAnims:
    d = items.model_dump(by_alias=True)
    d[phase] = val
    return ItemAnims.model_validate(d)


# --- punti di transizione: tagli e cambi di scena ------------------------------------------

SCENE_DIFF = 28.0  # differenza media (0-255) tra i fotogrammi ai due lati: oltre = altra scena
BLOCK_GAP_MS = 1500


def _gray(video: Path, at_ms: int) -> bytes | None:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, at_ms) / 1000:.3f}", "-i", str(video),
           "-frames:v", "1", "-vf", "scale=24:42,format=gray", "-f", "rawvideo", "-"]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=True).stdout
    except Exception:  # analisi "se si riesce": senza, l'editor funziona lo stesso
        return None
    return out or None


def frame_diff(video: Path, a_ms: int, b_ms: int) -> float | None:
    a, b = _gray(video, a_ms), _gray(video, b_ms)
    if not a or not b or len(a) != len(b):
        return None
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def detect_scenes(video: Path, threshold: float = 0.35) -> list[int]:
    """Cambi di inquadratura dentro il girato (ffmpeg scene detection), in ms del file."""
    cmd = ["ffmpeg", "-v", "info", "-i", str(video), "-an", "-vf",
           f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]  # fmt: skip
    try:
        err = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stderr
    except Exception:  # analisi "se si riesce": senza, l'editor funziona lo stesso
        return []
    out = []
    for line in err.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            try:
                out.append(round(float(line.split("pts_time:")[1].split()[0]) * 1000))
            except ValueError:
                continue
    return out


def boundaries(
    tl: Timeline,
    eff: list[EffectiveRange],
    *,
    video: Path | None,
    offset_ms: int,
    cache_path: Path | None,
) -> list[dict[str, Any]]:
    """Dove due clip si toccano nel montato: ogni taglio (parte tolta tra due tenute) e ogni
    cambio di scena dentro una parte tenuta. kind = "scene" se l'immagine cambia davvero."""
    cache: dict[str, Any] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    diffs: dict[str, float | None] = cache.get("diffs", {})
    scenes: list[int] | None = cache.get("scenes")
    if scenes is None and video is not None:
        scenes = [ms + offset_ms for ms in detect_scenes(video)]
    out: list[dict[str, Any]] = []
    for i, r in enumerate(eff):
        if r.state != "remove" or i == 0 or i == len(eff) - 1:
            continue
        if eff[i - 1].state != "keep" or eff[i + 1].state != "keep":
            continue
        key = f"{r.start_ms}-{r.end_ms}"
        if key not in diffs and video is not None:
            diffs[key] = frame_diff(video, r.start_ms - offset_ms - 40, r.end_ms - offset_ms + 40)
        d = diffs.get(key)
        gap = r.end_ms - r.start_ms
        out.append({
            "id": r.source_id, "at_ms": r.start_ms, "end_ms": r.end_ms, "gap_ms": gap,
            "diff": None if d is None else round(d, 1),
            "kind": "scene" if d is not None and d >= SCENE_DIFF else "cut",
            "block": gap >= BLOCK_GAP_MS,
        })  # fmt: skip
    for ms in scenes or []:
        if any(r.state == "keep" and r.start_ms + 300 < ms < r.end_ms - 300 for r in eff):
            out.append({"id": f"scene:{ms}", "at_ms": ms, "end_ms": ms, "gap_ms": 0, "diff": None,
                        "kind": "scene", "block": False})  # fmt: skip
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"diffs": diffs, "scenes": scenes or []}), encoding="utf-8"
        )
    return sorted(out, key=lambda b: b["at_ms"])


# --- Claude compone il preset ---------------------------------------------------------------

STYLE_LOGIC = {
    P: (
        "PREMIUM (elegante, costoso): movimenti lenti e morbidi, niente rimbalzi o giri. Testo: "
        "words_blur / rise / fade, uscita fade o sink. Sticker: rise o blur_in, uscita fade, loop "
        "quasi mai (al massimo float lento). Transizioni solo dove c'è davvero un cambio di scena o "
        "di argomento (blur, dip_black, fade, wipe_left), 400-700 ms; sui jump cut normali taglio netto."
    ),
    V: (
        "VIRAL (marketing, provinciale, ritmo alto): effetti d'impatto ma non a caso. Testo: pop / "
        "words_pop, a volte zoom_big sui concetti forti. Sticker: pop, bounce, drop, spin_in; uscita "
        "zoom_out o pop_out; loop wiggle/pulse/heartbeat per 1-2 sticker importanti. Transizioni "
        "brevi (200-350 ms): whip o zoom ai cambi di scena e di blocco, flash su un momento forte; "
        "sui jump cut di una frase che continua, taglio netto (lo zoom secco c'è già)."
    ),
}

_SCHEMA = """Rispondi SOLO con un oggetto JSON:
{"captions": {"in": {"type": "...", "ms": 300}, "out": {"type": "...", "ms": 250}},
 "sticker_default": {"in": {...}, "out": {...}, "loop": {"type": "none", "ms": 0, "speed": 1}},
 "stickers": {"pop_0007": {"in": {...}, "out": {...}, "loop": {...}}},
 "transitions": {"<id punto>": {"type": "...", "ms": 300}},
 "message": "spiegazione breve in italiano di cosa hai scelto e perché: usa i nomi italiani degli effetti tra parentesi nella galleria (es. «Pop parola per parola», «Whip»), mai gli id tecnici"}
Metti in "stickers" solo quelli che meritano un effetto diverso dal predefinito; in
"transitions" solo i punti dove serve (gli altri restano taglio netto)."""


def suggest_prompt(
    style_id: str | None,
    style_name: str,
    words: list[tuple[str, str, int]],
    points: list[dict[str, Any]],
    stickers: list[dict[str, Any]],
) -> str:
    sid = _key(style_id)
    gallery = {
        ph: [f"{a['id']} ({a['label']})" for a in ANIMS if a["phase"] == ph and sid in a["sets"]]
        for ph in ("in", "out", "loop")
    }
    trans = [f"{t['id']} ({t['label']})" for t in TRANSITIONS if sid in t["sets"]]
    lines = "\n".join(f"{ms / 1000:7.2f}s  {text}" for _, text, ms in words)
    pts = (
        "\n".join(
            f"- {b['id']} @ {b['at_ms'] / 1000:.2f}s  {b['kind']}"
            f"{' (dopo una pausa lunga: nuovo blocco)' if b.get('block') else ''}"
            f"  differenza immagine {b['diff'] if b['diff'] is not None else '?'}"
            for b in points
        )
        or "(nessuno)"
    )
    sts = (
        "\n".join(
            f"- {s['id']} @ {s['at_ms'] / 1000:.2f}s  {s.get('emoji') or s.get('title') or s['kind']}"
            for s in stickers
        )
        or "(nessuno)"
    )
    return f"""Sei il motion designer di un video verticale in italiano, stile «{style_name}».
Componi gli effetti: animazioni del testo (sottotitoli), degli sticker e transizioni tra clip.
{STYLE_LOGIC[sid]}

Galleria di questo stile (usa SOLO questi id):
- entrata: {", ".join(gallery["in"])}
- uscita: {", ".join(gallery["out"])}
- loop (solo sticker): {", ".join(gallery["loop"])}
- transizioni: {", ".join(trans)}
Durate in ms: entrata 150-900, uscita 120-700, transizioni 150-900.

Parlato (tempo di inizio, parola):
{lines}

Punti dove due clip si toccano (id, tempo, tipo):
{pts}

Sticker nel video:
{sts}

{_SCHEMA}"""


def apply_suggestion(
    data: EffectsFile, style_id: str | None, ops: dict[str, Any], *, sticker_ids: set[str],
    point_ids: set[str],
) -> tuple[EffectsFile, str]:  # fmt: skip
    """Applica la proposta di Claude scartando quello che non è valido (id o effetti)."""
    sid = _key(style_id)
    allowed = {ph: {a["id"] for a in ANIMS if a["phase"] == ph and sid in a["sets"]}
               for ph in ("in", "out", "loop")}  # fmt: skip
    trans_ok = {t["id"] for t in TRANSITIONS if sid in t["sets"]}

    def anims(d: Any, text: bool) -> ItemAnims | None:
        if not isinstance(d, dict):
            return None
        out = {}
        for ph in ("in", "out", "loop"):
            spec = d.get(ph)
            if not isinstance(spec, dict) or (text and ph == "loop"):
                continue
            ok = allowed[ph] & anim_ids(ph, text)
            if spec.get("type") not in ok:
                continue
            try:
                out[ph] = Anim.model_validate(
                    {k: spec[k] for k in ("type", "ms", "speed") if k in spec}
                )
            except ValueError:
                continue
        return ItemAnims.model_validate(out) if out else None

    key = style_id or "_none"
    cur = (data.styles.get(key) or StyleEffects()).model_copy(deep=True)
    if (c := anims(ops.get("captions"), True)) is not None:
        cur.captions = c
    if (s := anims(ops.get("sticker_default"), False)) is not None:
        cur.sticker_default = s
    stickers = {}
    for pid, d in (ops.get("stickers") or {}).items():
        if pid in sticker_ids and (a := anims(d, False)) is not None:
            stickers[pid] = a
    cur.stickers = stickers
    trans = {k: v for k, v in cur.transitions.items() if v.origin == "user"}  # le tue restano
    for bid, t in (ops.get("transitions") or {}).items():
        if (
            bid in point_ids
            and bid not in trans
            and isinstance(t, dict)
            and t.get("type") in trans_ok
        ):
            try:
                trans[bid] = Transition.model_validate(
                    {"type": t["type"], "ms": t.get("ms", 300), "origin": "ai"}
                )
            except ValueError:
                continue
    cur.transitions = trans
    cur.suggested = True
    cur.note = str(ops.get("message") or "")[:400]
    styles = dict(data.styles)
    styles[key] = cur
    return EffectsFile(version=data.version, styles=styles), cur.note
