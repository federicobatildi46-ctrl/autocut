"""Emoji come immagini (stile iPhone) per sticker e pop-up.

library/emoji/ (fuori da git) contiene i PNG estratti dal font Apple Color Emoji
(github.com/samuelngs/apple-emoji-ttf) e index.json con le categorie della tastiera.
Sono disegni di Apple: solo per uso personale, non per i video dei clienti.
Se la cartella manca, editor e render usano il font Noto Color Emoji come prima.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .paths import REPO_ROOT

EMOJI_DIR = REPO_ROOT / "library" / "emoji"
NAME_RE = re.compile(r"^[0-9a-f]{2,6}(-[0-9a-f]{2,6})*\.png$")
_VS16 = "️"


def key(seq: str) -> str:
    return seq.replace(_VS16, "")


@lru_cache(maxsize=4)
def _load(root: str) -> dict:
    path = Path(root) / "index.json"
    if not path.exists():
        return {"categories": [], "map": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = {key(i["e"]): i["img"] for c in data["categories"] for i in c["items"]}
    return {**data, "map": mapping}


def index(root: Path = EMOJI_DIR) -> dict:
    return _load(str(root))


def available(root: Path = EMOJI_DIR) -> bool:
    return bool(index(root)["map"])


def split(text: str, root: Path = EMOJI_DIR) -> list[tuple[str, str | None]]:
    """Divide in emoji (sequenza più lunga che esiste: bandiere, famiglie, mestieri…)."""
    mapping = index(root)["map"]
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(text):
        if text[i] == _VS16 or text[i].isspace():
            i += 1
            continue
        found = None
        for j in range(min(len(text), i + 14), i, -1):
            img = mapping.get(key(text[i:j]))
            if img:
                found = (text[i:j], img)
                break
        if found:
            out.append(found)
            i += len(found[0])
        else:
            out.append((text[i], None))
            i += 1
    return out


def images_for(text: str, root: Path = EMOJI_DIR) -> list[str] | None:
    """Nomi dei PNG delle emoji del testo, o None se anche una sola non c'è."""
    parts = split(text, root)
    if not parts or any(img is None for _, img in parts):
        return None
    return [img for _, img in parts if img]
