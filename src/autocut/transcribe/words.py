"""Dalla risposta di Scribe alle parole della timeline (ms interi sull'asse camera)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..ids import word_id
from ..models.timeline import Word

KEPT_TYPES = {"word", "audio_event"}  # "spacing" (gli spazi) non serve


def words_from_response(response: Mapping[str, Any], offset_ms: int = 0) -> list[Word]:
    items = []
    for order, item in enumerate(response.get("words") or []):
        kind = item.get("type")
        text = str(item.get("text") or "").strip()
        start, end = item.get("start"), item.get("end")
        if kind not in KEPT_TYPES or not text or start is None or end is None:
            continue
        if kind == "word" and not any(ch.isalnum() for ch in text):
            continue  # punteggiatura isolata (es. "." dopo un evento): non è parlato
        start_ms = round(float(start) * 1000) + offset_ms
        end_ms = max(start_ms, round(float(end) * 1000) + offset_ms)
        logprob = item.get("logprob")
        items.append((start_ms, order, end_ms, text, kind, logprob))

    items.sort(key=lambda t: (t[0], t[1]))
    return [
        Word(
            id=word_id(n),
            text=text,
            start_ms=start_ms,
            end_ms=end_ms,
            kind=kind,
            logprob=round(float(logprob), 4) if logprob is not None else None,
        )
        for n, (start_ms, _, end_ms, text, kind, logprob) in enumerate(items, start=1)
    ]
