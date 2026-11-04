"""Id stabili delle decisioni automatiche.

Gli id sono ancorati agli id delle parole, non ai tempi: cambiare soglia o margine non
invalida gli override finché la decisione esiste ancora (es. una pausa che resta una pausa).
"""

from __future__ import annotations

import re

HEAD = "^"  # prima della prima parola
TAIL = "$"  # dopo l'ultima parola

WORD_RE = re.compile(r"^w\d{6,}$")


def word_id(index: int) -> str:
    """Id della parola con indice (1-based) nella trascrizione."""
    if index < 1:
        raise ValueError("l'indice di una parola parte da 1")
    return f"w{index:06d}"


def gap_id(prev_word: str | None, next_word: str | None) -> str:
    """Pausa tra due parole; None = bordo del video (testa/coda).

    Entrambe None = nessun parlato nel tratto: "gap:^-$".
    """
    return f"gap:{prev_word or HEAD}-{next_word or TAIL}"


def segment_id(first_word: str, last_word: str) -> str:
    """Tratto di parlato tenuto, dalla prima all'ultima parola."""
    return f"seg:{first_word}-{last_word}"


def group_id(first_word: str) -> str:
    """Gruppo di ripetizioni, ancorato alla prima parola della prima presa."""
    return f"rg:{first_word}"


def take_id(first_word: str) -> str:
    """Presa, ancorata alla sua prima parola."""
    return f"take:{first_word}"


def proposal_id(group: str) -> str:
    """Proposta di un gruppo di ripetizioni."""
    return f"prop:{group}"


def kind_of(identifier: str) -> str:
    """Prefisso dell'id (w, gap, seg, rg, take, prop)."""
    if WORD_RE.match(identifier):
        return "w"
    prefix, sep, _ = identifier.partition(":")
    if not sep:
        raise ValueError(f"id non riconosciuto: {identifier!r}")
    return prefix
