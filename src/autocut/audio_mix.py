"""Pannello Audio: volume della voce, degli effetti sonori e di ogni singolo suono.

I suoni li sceglie lo stile in automatico (preview.plan_sounds sull'intero video); qui si
salvano solo le correzioni dell'utente, per stile, in projects/<nome>/audio.json:
- voce: dB rispetto alla voce già normalizzata (o muta);
- effetti: dB per tutti gli effetti (o tutti muti);
- ogni suono automatico (id "auto:<tipo evento>:<ms del raw>"): muto, dB, altro suono, spostato;
- suoni aggiunti a mano alla testina (id "snd_0001").
Editor e render usano la stessa lista (resolve), con i tempi sul raw.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .render.preview import RenderError, build_props, sound_gain_db, to_raw

AUDIO_FILE = "audio.json"
FAMILY_LABEL = {"whooshes": "Whoosh", "textures": "Effetti", "risers": "Riser", "hits": "Colpi"}


class SoundEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    muted: bool = False
    gain_db: float = Field(default=0.0, ge=-30, le=12)  # rispetto al livello automatico
    type: str | None = None  # altro suono della libreria
    shift_ms: int = Field(default=0, ge=-10000, le=10000)  # spostato nella timeline


class AddedSound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^snd_\d{4,}$")
    type: str
    at_ms: int = Field(ge=0)  # istante del raw (picco del suono)
    gain_db: float = Field(default=0.0, ge=-30, le=12)
    muted: bool = False


class StyleAudio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_db: float = Field(default=0.0, ge=-24, le=12)
    voice_muted: bool = False
    sfx_db: float = Field(default=0.0, ge=-30, le=12)
    sfx_muted: bool = False
    sounds: dict[str, SoundEdit] = Field(default_factory=dict)
    added: list[AddedSound] = Field(default_factory=list)


class AudioFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    styles: dict[str, StyleAudio] = Field(default_factory=dict)  # "" = nessuno stile


class AudioError(ValueError):
    pass


def load(project_dir: Path) -> AudioFile:
    p = project_dir / AUDIO_FILE
    if not p.exists():
        return AudioFile()
    try:
        return AudioFile.model_validate_json(p.read_bytes())
    except ValidationError as exc:
        raise AudioError(f"{p}: {exc}") from exc


def save(project_dir: Path, data: AudioFile) -> None:
    p = project_dir / AUDIO_FILE
    tmp = p.with_suffix(".partial")
    body = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def for_style(data: AudioFile, style: str | None) -> StyleAudio:
    return data.styles.get(style or "", StyleAudio())


def _with(data: AudioFile, style: str | None, sa: StyleAudio) -> AudioFile:
    return data.model_copy(update={"styles": {**data.styles, style or "": sa}})


def update(
    data: AudioFile,
    style: str | None,
    *,
    target: str,
    item: str | None = None,
    fields: dict[str, Any] | None = None,
    catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> AudioFile:
    """target: mix (voce/effetti) | sound (un suono) | add | remove | reset."""
    sa = for_style(data, style)
    fields = dict(fields or {})
    known = set(catalog or {})
    if fields.get("type") is not None and catalog is not None and fields["type"] not in known:
        raise AudioError(f"suono {fields['type']!r} non è nella libreria")
    try:
        if target == "mix":
            allowed = {"voice_db", "voice_muted", "sfx_db", "sfx_muted"}
            bad = set(fields) - allowed
            if bad:
                raise AudioError(f"campi sconosciuti: {sorted(bad)}")
            sa = StyleAudio.model_validate({**sa.model_dump(), **fields})
        elif target == "sound":
            if not item:
                raise AudioError("manca il suono")
            if item.startswith("snd_"):
                added = []
                for a in sa.added:
                    if a.id == item:
                        upd = {k: v for k, v in fields.items() if k in {"gain_db", "muted", "type"}}
                        if "shift_ms" in fields:
                            upd["at_ms"] = max(0, a.at_ms + int(fields["shift_ms"]))
                        a = AddedSound.model_validate({**a.model_dump(), **upd})
                    added.append(a)
                if not any(a.id == item for a in sa.added):
                    raise AudioError(f"suono {item} non trovato")
                sa = sa.model_copy(update={"added": added})
            else:
                cur = sa.sounds.get(item, SoundEdit()).model_dump()
                if "shift_ms" in fields:
                    fields["shift_ms"] = cur["shift_ms"] + int(fields["shift_ms"])
                edit = SoundEdit.model_validate({**cur, **fields})
                sounds = {**sa.sounds, item: edit}
                if edit == SoundEdit():
                    sounds.pop(item)
                sa = sa.model_copy(update={"sounds": sounds})
        elif target == "add":
            if not fields.get("type") or "at_ms" not in fields:
                raise AudioError("per aggiungere un suono servono tipo e istante")
            nums = [int(a.id[4:]) for a in sa.added]
            new = AddedSound(
                id=f"snd_{(max(nums) + 1 if nums else 1):04d}",
                type=fields["type"],
                at_ms=int(fields["at_ms"]),
                gain_db=float(fields.get("gain_db", 0.0)),
            )
            sa = sa.model_copy(update={"added": [*sa.added, new]})
        elif target == "remove":
            if item and item.startswith("snd_"):
                sa = sa.model_copy(update={"added": [a for a in sa.added if a.id != item]})
            elif item:  # un suono automatico non si cancella: si mette muto
                cur = sa.sounds.get(item, SoundEdit())
                sa = sa.model_copy(
                    update={"sounds": {**sa.sounds, item: cur.model_copy(update={"muted": True})}}
                )  # noqa: E501
        elif target == "reset":
            if item:
                sa = sa.model_copy(
                    update={"sounds": {k: v for k, v in sa.sounds.items() if k != item}}
                )  # noqa: E501
            else:
                sa = StyleAudio()
        else:
            raise AudioError(f"azione {target!r} sconosciuta")
    except ValidationError as exc:
        raise AudioError(exc.errors()[0]["msg"]) from exc
    return _with(data, style, sa)


# --- piano dei suoni -------------------------------------------------------------------


def auto_plan(*, end_ms: int, **props_kwargs: Any) -> list[dict[str, Any]]:
    """Suoni che lo stile mette da solo su tutto il video, con i tempi del raw.

    Stessa scelta del render (preview.plan_sounds), calcolata una volta sull'intero montato,
    così editor e render hanno gli stessi suoni negli stessi punti."""
    try:
        props, pieces = build_props(window=(0, end_ms), source_rel="", **props_kwargs)
    except RenderError:
        return []  # è tutto tagliato
    out = []
    for s in props["sounds"]:
        at = to_raw(pieces, s["event_ms"])
        out.append(
            {
                "id": f"auto:{s['kind']}:{at}",
                "type": s["type"],
                "file": s["file"],
                "kind": s["kind"],
                "reason": s["reason"],
                "at_ms": at,
                "lead_ms": s["event_ms"] - s["from_ms"],
                "base_db": s["gain_db"],
            }
        )
    return out


def _variant(catalog: dict[str, list[dict[str, Any]]], kind: str) -> dict[str, Any] | None:
    variants = catalog.get(kind) or []
    return variants[0] if variants else None


def resolve(
    plan: list[dict[str, Any]],
    sa: StyleAudio,
    look: dict[str, Any] | None,
    catalog: dict[str, list[dict[str, Any]]],
    loudness: Callable[[dict[str, Any]], float | None] = lambda s: None,
) -> list[dict[str, Any]]:
    """Piano automatico + correzioni dell'utente → suoni finali (tempi del raw, dB finali)."""
    out = []

    def entry(base: dict[str, Any], v: dict[str, Any] | None, offset: float, muted: bool):
        lead = int(v.get("peak_ms", 0)) if v else base.get("lead_ms", 0)
        b = sound_gain_db(look, v, loudness) if (v and look) else base.get("base_db", -24.0)
        return {
            **base,
            "file": v["file"] if v else base["file"],
            "label": v.get("label", base["type"]) if v else base["type"],
            "family": v.get("family", "textures") if v else "textures",
            "duration_ms": int(v.get("duration_ms", 800)) if v else 800,
            "lead_ms": lead,
            "base_db": round(b, 1),
            "offset_db": offset,
            "own_muted": muted,
            "gain_db": round(b + offset + sa.sfx_db, 1),
            "muted": muted or sa.sfx_muted,
        }

    for s in plan:
        e = sa.sounds.get(s["id"], SoundEdit())
        kind = e.type or s["type"]
        v = _variant(catalog, kind) if e.type else next(
            (x for x in catalog.get(kind, []) if x["file"] == s["file"]), None
        )  # fmt: skip
        base = {**s, "type": kind, "at_ms": max(0, s["at_ms"] + e.shift_ms), "origin": "auto",
                "edited": e != SoundEdit()}  # fmt: skip
        out.append(entry(base, v, e.gain_db, e.muted))
    for a in sa.added:
        v = _variant(catalog, a.type)
        if v is None:
            continue  # suono non più in libreria
        base = {"id": a.id, "type": a.type, "file": v["file"], "kind": "user",
                "reason": "aggiunto da te", "at_ms": a.at_ms, "origin": "user",
                "edited": True}  # fmt: skip
        out.append(entry(base, v, a.gain_db, a.muted))
    return sorted(out, key=lambda s: (s["at_ms"], s["id"]))


def voice_offset_db(sa: StyleAudio) -> float:
    """Quanto alzare/abbassare la voce rispetto alla normalizzazione (-80 = muta)."""
    return -80.0 if sa.voice_muted else sa.voice_db


def library(catalog: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Suoni che si possono aggiungere o mettere al posto di un altro (uno per tipo)."""
    out = []
    for kind, variants in sorted(catalog.items()):
        v = variants[0]
        out.append(
            {
                "type": kind,
                "label": v.get("label", kind),
                "family": v.get("family", "textures"),
                "family_label": FAMILY_LABEL.get(v.get("family", ""), "Effetti"),
                "usage": v.get("usage", ""),
                "duration_ms": int(v.get("duration_ms", 800)),
                "url": "/media/sfx/" + v["file"],
            }
        )
    return out
