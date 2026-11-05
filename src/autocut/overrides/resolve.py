"""Vista effettiva: proposte del motore + override attivi (gli orfani non si applicano mai).

Restituisce una lista di intervalli contigui con lo stato effettivo (keep/remove) e la loro
origine: "proposal" (decisione del motore), "override" (scelta dell'utente) o "take"
(presa non scelta di un gruppo di ripetizioni).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..models.overrides import OverridesFile
from ..models.timeline import Timeline


@dataclass(frozen=True)
class EffectiveRange:
    start_ms: int
    end_ms: int
    state: str  # keep | remove
    source_id: str  # id del segmento o della presa
    origin: str  # proposal | override | take

    def to_dict(self) -> dict:
        return asdict(self)


def _active(ov: OverridesFile | None, target_id: str):
    if ov is None:
        return None
    o = ov.overrides.get(target_id)
    return o if o is not None and o.status == "active" else None


def take_removals(tl: Timeline, ov: OverridesFile | None) -> list[tuple[int, int, str]]:
    """Intervalli delle prese da togliere, secondo proposta o scelta dell'utente."""
    out: list[tuple[int, int, str]] = []
    for group in tl.repeat_groups:
        o = _active(ov, group.id)
        if o is not None:
            chosen = o.value.get("take_id")
        elif group.proposal is not None:
            chosen = group.proposal.take_id
        else:
            chosen = None  # ambiguo senza scelta: non si toglie niente
        if chosen is None:
            continue
        out += [(t.start_ms, t.end_ms, t.id) for t in group.takes if t.id != chosen]
    return sorted(out)


def effective_ranges(tl: Timeline, ov: OverridesFile | None) -> list[EffectiveRange]:
    base: list[EffectiveRange] = []
    for seg in tl.segments:
        o = _active(ov, seg.id)
        state = o.value["state"] if o is not None else seg.state
        base.append(
            EffectiveRange(seg.start_ms, seg.end_ms, state, seg.id, "override" if o else "proposal")
        )

    takes = take_removals(tl, ov)
    if not takes:
        return base

    out: list[EffectiveRange] = []
    for r in base:
        if r.state != "keep":
            out.append(r)
            continue
        cursor = r.start_ms
        for start, end, take in takes:
            if end <= cursor or start >= r.end_ms:
                continue
            if start > cursor:
                out.append(EffectiveRange(cursor, start, "keep", r.source_id, r.origin))
            cut_end = min(end, r.end_ms)
            out.append(EffectiveRange(max(start, cursor), cut_end, "remove", take, "take"))
            cursor = cut_end
        if cursor < r.end_ms:
            out.append(EffectiveRange(cursor, r.end_ms, "keep", r.source_id, r.origin))
    return out


def kept_ms(ranges: list[EffectiveRange]) -> int:
    return sum(r.end_ms - r.start_ms for r in ranges if r.state == "keep")
