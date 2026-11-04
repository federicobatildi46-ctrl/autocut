"""Pause morte -> segmenti tenuti/tolti (calcolo puro, senza file).

Regola:
- "parlato" = parole + eventi audio che proteggono il parlato (vedi autocut.events);
  gli eventi "morti" (es. [esita]) contano come silenzio;
- una pausa tra due tratti di parlato si toglie se dura >= threshold_ms;
- la parte tolta lascia margin_ms per lato attaccati al parlato (testa del video: nessun
  margine prima dell'inizio; coda: nessun margine dopo la fine);
- i segmenti coprono tutto l'asse [inizio, fine], contigui e senza sovrapposizioni.

Id stabili ancorati alle parole: gap:<prima>-<dopo> per le pause, seg:<prima>-<ultima> per i
tratti tenuti. Cambiare soglia o margine non cambia l'id di una pausa che resta una pausa.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..events import event_tag, is_dead_event, protects_speech
from ..ids import gap_id, segment_id
from ..models.timeline import PauseSettings, Segment, TranscriptionSettings, Word


@dataclass(frozen=True)
class _Removal:
    start_ms: int
    end_ms: int
    prev: Word | None
    next: Word | None
    gap_ms: int


def _reason(r: _Removal, threshold_ms: int, margin_ms: int, dead: Sequence[Word]) -> str:
    if r.prev is None and r.next is None:
        return "nessun parlato nel tratto"
    if r.prev is None:
        what = f"silenzio iniziale {r.gap_ms} ms"
        edge = f"margine {margin_ms} ms prima della prima parola"
    elif r.next is None:
        what = f"silenzio finale {r.gap_ms} ms"
        edge = f"margine {margin_ms} ms dopo l'ultima parola"
    else:
        what = f"pausa {r.gap_ms} ms"
        edge = f"margine {margin_ms} ms per lato"
    if dead:
        what += " (con " + ", ".join(w.text for w in dead) + ")"
    return f"{what} >= soglia {threshold_ms} ms; {edge}"


def compute_segments(
    words: Sequence[Word],
    *,
    axis_start_ms: int,
    axis_end_ms: int,
    pauses: PauseSettings,
    transcription: TranscriptionSettings,
) -> list[Segment]:
    if axis_end_ms <= axis_start_ms:
        raise ValueError("asse vuoto: la fine deve venire dopo l'inizio")
    thr, margin = pauses.threshold_ms, pauses.margin_ms

    in_axis = [w for w in words if w.end_ms > axis_start_ms and w.start_ms < axis_end_ms]
    speech = [w for w in in_axis if protects_speech(w, transcription)]
    dead = [w for w in in_axis if is_dead_event(w, transcription)]

    def dead_inside(start: int, end: int) -> list[Word]:
        return [w for w in dead if w.start_ms < end and w.end_ms > start]

    def removal_segment(r: _Removal) -> Segment:
        inside = dead_inside(r.start_ms, r.end_ms)
        data: dict = {"gap_ms": r.gap_ms, "threshold_ms": thr, "margin_ms": margin}
        if inside:
            data["dead_events"] = [{"id": w.id, "tag": event_tag(w.text)} for w in inside]
        return Segment(
            id=gap_id(r.prev.id if r.prev else None, r.next.id if r.next else None),
            state="remove",
            type="dead_pause",
            start_ms=r.start_ms,
            end_ms=r.end_ms,
            reason=_reason(r, thr, margin, inside),
            data=data,
        )

    if not speech:
        whole = _Removal(axis_start_ms, axis_end_ms, None, None, axis_end_ms - axis_start_ms)
        return [removal_segment(whole)]

    removals: list[_Removal] = []

    first = speech[0]
    head_gap = max(0, first.start_ms - axis_start_ms)
    if head_gap >= thr and first.start_ms - margin > axis_start_ms:
        removals.append(_Removal(axis_start_ms, first.start_ms - margin, None, first, head_gap))

    prev, prev_end = first, min(first.end_ms, axis_end_ms)
    for word in speech[1:]:
        gap = word.start_ms - prev_end
        start, end = prev_end + margin, word.start_ms - margin
        if gap >= thr and end > start:
            removals.append(_Removal(start, end, prev, word, gap))
        prev, prev_end = word, max(prev_end, min(word.end_ms, axis_end_ms))

    tail_gap = axis_end_ms - prev_end
    if tail_gap >= thr and prev_end + margin < axis_end_ms:
        removals.append(_Removal(prev_end + margin, axis_end_ms, prev, None, tail_gap))

    segments: list[Segment] = []
    cursor = axis_start_ms
    keep_first = speech[0]
    for r in removals:
        if r.start_ms > cursor:
            assert r.prev is not None  # un tratto tenuto prima di una pausa ha parlato
            segments.append(_keep(cursor, r.start_ms, keep_first, r.prev, margin))
        segments.append(removal_segment(r))
        cursor = r.end_ms
        if r.next is not None:
            keep_first = r.next
    if cursor < axis_end_ms:
        segments.append(_keep(cursor, axis_end_ms, keep_first, speech[-1], margin))
    return segments


def _keep(start: int, end: int, first: Word, last: Word, margin: int) -> Segment:
    return Segment(
        id=segment_id(first.id, last.id),
        state="keep",
        type="speech",
        start_ms=start,
        end_ms=end,
        reason=f"parlato (margine {margin} ms per lato)",
        data={"word_span": [first.id, last.id]},
    )
