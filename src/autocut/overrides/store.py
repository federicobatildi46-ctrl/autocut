"""Correzioni dell'utente sopra le proposte: overrides.json, mai dentro la timeline.

- Ogni override punta all'id stabile della proposta che ribalta (segmento o gruppo).
- Ogni modifica aggiunge una voce alla cronologia (append-only): create / update / remove.
- L'undo è a sua volta una voce (`undo`, `reverts=<seq>`) che ripristina il valore `before`.
- `reconcile` segnala come orfani gli override la cui proposta non esiste più nella timeline
  (es. dopo un cambio di soglia) e li riattiva se la proposta ricompare. Un orfano non viene
  mai applicato.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.io import read_model, write_model
from ..models.overrides import (
    HistoryEntry,
    Override,
    OverridesFile,
    Target,
    TimelineRef,
)
from ..models.timeline import RepeatGroup, Segment, Timeline
from ..paths import OVERRIDES_FILE

ACTIONS = ("create", "update", "remove")


class OverrideError(ValueError):
    pass


def now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def overrides_path(project_dir: Path) -> Path:
    return project_dir / OVERRIDES_FILE


def load(project_dir: Path, tl: Timeline) -> OverridesFile:
    path = overrides_path(project_dir)
    if path.exists():
        return read_model(path, OverridesFile)
    return OverridesFile(
        timeline_ref=TimelineRef(project=tl.project.name, timeline_schema_version=tl.schema_version)
    )


def save(project_dir: Path, ov: OverridesFile) -> None:
    write_model(overrides_path(project_dir), ov)


# --- ricerca delle proposte ------------------------------------------------------------


def find_target(tl: Timeline, target_id: str) -> Segment | RepeatGroup | None:
    for seg in tl.segments:
        if seg.id == target_id:
            return seg
    for group in tl.repeat_groups:
        if group.id == target_id:
            return group
    return None


def _words_text(tl: Timeline, start_ms: int, end_ms: int, limit: int = 12) -> str:
    words = [w.text for w in tl.words if w.start_ms < end_ms and w.end_ms > start_ms]
    text = " ".join(words[:limit])
    return text + (" …" if len(words) > limit else "")


def _snapshot(tl: Timeline, target: Segment | RepeatGroup) -> dict[str, Any]:
    if isinstance(target, Segment):
        return {
            "start_ms": target.start_ms,
            "end_ms": target.end_ms,
            "state": target.state,
            "reason": target.reason,
            "text": _words_text(tl, target.start_ms, target.end_ms),
        }
    return {"takes": [{"id": t.id, "text": t.text} for t in target.takes]}


def _proposed(target: Segment | RepeatGroup) -> dict[str, Any]:
    if isinstance(target, Segment):
        return {"state": target.state}
    return {"take_id": target.proposal.take_id if target.proposal else None}


def _build(
    tl: Timeline, target_id: str, value: dict[str, Any], override_id: str, note: str | None
) -> Override:
    target = find_target(tl, target_id)
    if target is None:
        raise OverrideError(f"nessuna proposta con id {target_id!r} nella timeline")
    if isinstance(target, Segment):
        if value.get("state") not in ("keep", "remove"):
            raise OverrideError("per un segmento il valore è {'state': 'keep'|'remove'}")
        action, kind = "set_state", "segment"
    else:
        take = value.get("take_id")
        if take is not None and take not in {t.id for t in target.takes}:
            raise OverrideError(f"la presa {take!r} non fa parte del gruppo {target_id}")
        action, kind = "choose_take", "repeat_group"
    return Override(
        id=override_id,
        target=Target(id=target_id, type=kind),
        action=action,
        value=dict(value),
        proposed=_proposed(target),
        status="active",
        snapshot=_snapshot(tl, target),
        note=note,
    )


def _next_id(ov: OverridesFile) -> str:
    used = {o.id for o in ov.overrides.values()} | {e.override_id for e in ov.history}
    numbers = [int(i[3:]) for i in used if i.startswith("ov_") and i[3:].isdigit()]
    return f"ov_{(max(numbers) + 1) if numbers else 1:04d}"


def _with(
    ov: OverridesFile, overrides: dict[str, Override], entry: dict[str, Any]
) -> OverridesFile:
    history = [*ov.history, HistoryEntry(seq=len(ov.history) + 1, at=now(), **entry)]
    return OverridesFile(
        schema_version=ov.schema_version,
        timeline_ref=ov.timeline_ref,
        overrides=overrides,
        history=history,
    )


# --- modifiche ---------------------------------------------------------------------------


def set_value(
    ov: OverridesFile,
    tl: Timeline,
    target_id: str,
    value: dict[str, Any],
    note: str | None = None,
) -> OverridesFile:
    """Imposta il valore scelto dall'utente. Se coincide con la proposta, l'override sparisce."""
    target = find_target(tl, target_id)
    if target is None:
        raise OverrideError(f"nessuna proposta con id {target_id!r} nella timeline")
    if dict(value) == _proposed(target):
        return clear(ov, target_id)

    existing = ov.overrides.get(target_id)
    if existing is not None and existing.value == value and existing.status == "active":
        return ov
    built = _build(tl, target_id, value, existing.id if existing else _next_id(ov), note)
    overrides = {**ov.overrides, target_id: built}
    entry = {
        "action": "update" if existing else "create",
        "override_id": built.id,
        "target_id": target_id,
        "before": existing.value if existing else None,
        "after": built.value,
    }
    return _with(ov, overrides, entry)


def clear(ov: OverridesFile, target_id: str) -> OverridesFile:
    """Torna alla proposta del motore."""
    existing = ov.overrides.get(target_id)
    if existing is None:
        return ov
    overrides = {k: v for k, v in ov.overrides.items() if k != target_id}
    entry = {
        "action": "remove",
        "override_id": existing.id,
        "target_id": target_id,
        "before": existing.value,
        "after": None,
    }
    return _with(ov, overrides, entry)


def last_undoable(ov: OverridesFile) -> HistoryEntry | None:
    reverted = {e.reverts for e in ov.history if e.action == "undo"}
    for entry in reversed(ov.history):
        if entry.action in ACTIONS and entry.seq not in reverted:
            return entry
    return None


def undo(ov: OverridesFile, tl: Timeline) -> OverridesFile:
    """Annulla l'ultima modifica non ancora annullata."""
    entry = last_undoable(ov)
    if entry is None:
        raise OverrideError("niente da annullare")
    target_id = entry.target_id
    overrides = dict(ov.overrides)
    if entry.before is None:
        overrides.pop(target_id, None)
    else:
        current = overrides.get(target_id)
        if find_target(tl, target_id) is not None:
            overrides[target_id] = _build(tl, target_id, entry.before, entry.override_id, None)
        elif current is not None:
            overrides[target_id] = current.model_copy(update={"value": dict(entry.before)})
        else:
            raise OverrideError(f"la proposta {target_id} non esiste più: non posso ripristinarla")
    return _with(
        ov,
        overrides,
        {
            "action": "undo",
            "override_id": entry.override_id,
            "target_id": target_id,
            "before": entry.after,
            "after": entry.before,
            "reverts": entry.seq,
        },
    )


def _still_valid(tl: Timeline, o: Override) -> bool:
    target = find_target(tl, o.target.id)
    if target is None:
        return False
    if o.action == "set_state":
        return isinstance(target, Segment)
    if not isinstance(target, RepeatGroup):
        return False
    take = o.value.get("take_id")
    return take is None or take in {t.id for t in target.takes}


def reconcile(ov: OverridesFile, tl: Timeline) -> tuple[OverridesFile, list[str], list[str]]:
    """Segna orfani gli override senza proposta; riattiva quelli la cui proposta è tornata."""
    orphaned: list[str] = []
    restored: list[str] = []
    result = ov
    for key in sorted(ov.overrides):
        o = result.overrides[key]
        valid = _still_valid(tl, o)
        if not valid and o.status == "active":
            new_status, action, bucket = "orphan", "orphaned", orphaned
        elif valid and o.status == "orphan":
            new_status, action, bucket = "active", "restored", restored
        else:
            continue
        overrides = {**result.overrides, key: o.model_copy(update={"status": new_status})}
        result = _with(
            result,
            overrides,
            {
                "action": action,
                "override_id": o.id,
                "target_id": key,
                "before": o.status,
                "after": new_status,
            },
        )
        bucket.append(key)
    return result, orphaned, restored
