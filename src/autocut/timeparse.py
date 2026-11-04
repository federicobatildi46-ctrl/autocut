"""Parsing di `--range`: `60-180`, `62.5-90`, `1:00-3:00`, `0:01:00-0:03:00` (secondi o [h:]m:s)."""

from __future__ import annotations

from .models.timeline import TimeRange


class RangeError(ValueError):
    pass


def parse_time_ms(text: str) -> int:
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or any(not p.strip() for p in parts):
        raise RangeError(f"tempo non valido: {text!r}")
    try:
        *whole, last = parts
        seconds = float(last)
        units = [int(p) for p in whole]
    except ValueError:
        raise RangeError(f"tempo non valido: {text!r}") from None
    if seconds < 0 or any(u < 0 for u in units):
        raise RangeError(f"tempo negativo: {text!r}")
    if units and seconds >= 60:
        raise RangeError(f"secondi oltre 59 in {text!r}")
    total = 0
    for u in units:
        total = total * 60 + u
    return round((total * 60 + seconds) * 1000) if units else round(seconds * 1000)


def parse_range(text: str) -> TimeRange:
    start, sep, end = text.partition("-")
    if not sep:
        raise RangeError(f"--range atteso come INIZIO-FINE, trovato {text!r}")
    rng_start, rng_end = parse_time_ms(start), parse_time_ms(end)
    if rng_end <= rng_start:
        raise RangeError(f"--range: la fine deve venire dopo l'inizio ({text!r})")
    return TimeRange(start_ms=rng_start, end_ms=rng_end)


def format_seconds(ms: int) -> str:
    """60000 -> "60", 62500 -> "62.5" (per i nomi delle cartelle)."""
    if ms % 1000 == 0:
        return str(ms // 1000)
    return f"{ms / 1000:.3f}".rstrip("0")
