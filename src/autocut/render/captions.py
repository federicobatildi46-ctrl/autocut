"""Sottotitoli per il render: divisione in frasi brevi e parola chiave da evidenziare.

Stesse regole dell'editor (static/app.js: buildChunks / emphasisIndex), così l'anteprima e il
render mostrano le stesse frasi. Se cambi una regola qui, cambiala anche là.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STOPWORDS = frozenset(
    (
        "il lo la i gli le un uno una di a da in con su per tra fra e ed o ma che chi cui non è era sono "
        "ho hai ha abbiamo avete hanno mi ti si ci vi ne del dello della dei degli delle al allo alla ai "
        "agli alle dal dalla dai nel nello nella nei nelle sul sulla sui questo questa questi quello quella "
        "io tu lui lei noi voi loro mio mia miei tuo tua suo sua come cosa più anche poi già qui lì così "
        "molto tutto tutti fare fatto essere stato sempre quando dove perché proprio ancora allora quindi "
        "vuole voglio vuoi volete vogliono posso puoi può possiamo devo deve dobbiamo dire detto faccio "
        "fanno vado andare provare proverò sapete sapere vedere guardare mettere prendere stesso stessa "
        "abbastanza veramente davvero praticamente semplicemente comunque insomma diciamo conseguenza "
        "eh ok the and a of to is it you"
    ).split()
)

_CLEAN = re.compile(r"[^\w]", re.UNICODE)
GAP_BREAK_MS = 350


@dataclass
class TimedWord:
    text: str
    start_ms: int
    end_ms: int
    kind: str = "word"


@dataclass
class Chunk:
    start_ms: int
    end_ms: int
    words: list[TimedWord] = field(default_factory=list)
    event: bool = False

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def clean_word(text: str) -> str:
    return _CLEAN.sub("", text.lower()).replace("_", "")


def emphasis_index(words: list[str]) -> int:
    """Indice della parola chiave: un numero, altrimenti la parola più lunga (>= 6 lettere)
    che non sia una stopword. -1 se nessuna è abbastanza forte."""
    best, score = -1, 0
    for i, w in enumerate(words):
        clean = clean_word(w)
        if not clean or clean in STOPWORDS:
            continue
        s = 100 if any(ch.isdigit() for ch in clean) else len(clean)
        if s > score:
            best, score = i, s
    return best if score >= 6 else -1


def build_chunks(words: list[TimedWord], max_words: int, max_chars: int) -> list[Chunk]:
    out: list[Chunk] = []
    cur: Chunk | None = None
    for w in words:
        event = w.kind == "audio_event"
        if cur is not None:
            last = cur.words[-1].text
            gap = w.start_ms - cur.end_ms > GAP_BREAK_MS
            full = len(cur.words) >= max_words or len(cur.text) + 1 + len(w.text) > max_chars
            punct = bool(re.search(r"[.?!,]$", last)) and len(cur.words) >= 2
        if cur is None or gap or full or punct or event or cur.event:
            cur = Chunk(w.start_ms, w.end_ms, [w], event)
            out.append(cur)
        else:
            cur.end_ms = w.end_ms
            cur.words.append(w)
    return out
