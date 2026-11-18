"""Tagli a mano dalla timeline (come CapCut): dividi alla testina, togli o rimetti un pezzo.

Stanno in projects/<nome>/cuts.json, sopra la vista effettiva (proposte del motore +
override): la timeline del motore non si tocca mai. Un pezzo tolto a mano vince su tutto;
rimetterlo lo toglie dalla lista. I punti di divisione servono solo a dividere i pezzi tenuti.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .overrides.resolve import EffectiveRange

CUTS_FILE = "cuts.json"
MIN_PIECE_MS = 40  # sotto un fotogramma e poco più non ha senso dividere


class CutsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    splits: list[int] = Field(default_factory=list)  # ms del raw, ordinati
    removed: list[tuple[int, int]] = Field(default_factory=list)  # [inizio, fine) tolti a mano


class CutError(ValueError):
    pass


def load(project_dir: Path) -> CutsFile:
    p = project_dir / CUTS_FILE
    if not p.exists():
        return CutsFile()
    return CutsFile.model_validate_json(p.read_bytes())


def save(project_dir: Path, data: CutsFile) -> None:
    p = project_dir / CUTS_FILE
    tmp = p.with_suffix(".partial")
    tmp.write_text(json.dumps(data.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(r for r in ranges if r[1] > r[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def split(data: CutsFile, ms: int) -> CutsFile:
    if any(abs(s - ms) < MIN_PIECE_MS for s in data.splits):
        raise CutError("c'è già una divisione qui")
    return data.model_copy(update={"splits": sorted([*data.splits, int(ms)])})


def unsplit(data: CutsFile, ms: int) -> CutsFile:
    near = [s for s in data.splits if abs(s - ms) <= 200]
    if not near:
        raise CutError("nessuna divisione vicino alla testina")
    drop = min(near, key=lambda s: abs(s - ms))
    return data.model_copy(update={"splits": [s for s in data.splits if s != drop]})


def remove(data: CutsFile, start: int, end: int) -> CutsFile:
    if end - start < MIN_PIECE_MS:
        raise CutError("pezzo troppo corto")
    return data.model_copy(update={"removed": _merge([*data.removed, (int(start), int(end))])})


def restore(data: CutsFile, start: int, end: int) -> CutsFile:
    """Rimette [start, end): toglie quella parte dai pezzi tolti a mano."""
    out: list[tuple[int, int]] = []
    for a, b in data.removed:
        if b <= start or a >= end:
            out.append((a, b))
            continue
        if a < start:
            out.append((a, start))
        if b > end:
            out.append((end, b))
    if out == data.removed:
        raise CutError("questo pezzo non è stato tolto a mano")
    return data.model_copy(update={"removed": _merge(out)})


def apply(eff: list[EffectiveRange], data: CutsFile) -> list[EffectiveRange]:
    """Vista effettiva con i pezzi tolti a mano (origine "manual", id "cut:inizio-fine")."""
    if not data.removed:
        return eff
    out: list[EffectiveRange] = []
    for r in eff:
        if r.state != "keep":
            out.append(r)
            continue
        cur = r.start_ms
        for a, b in data.removed:
            a, b = max(a, r.start_ms), min(b, r.end_ms)
            if b <= a:
                continue
            if a > cur:
                out.append(EffectiveRange(cur, a, "keep", r.source_id, r.origin))
            out.append(EffectiveRange(a, b, "remove", f"cut:{a}-{b}", "manual"))
            cur = b
        if cur < r.end_ms:
            out.append(EffectiveRange(cur, r.end_ms, "keep", r.source_id, r.origin))
    return out
