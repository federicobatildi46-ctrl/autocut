"""Pop-up del video: elementi che compaiono sopra il parlato (immagine, emoji, parola/numero).

Vivono in projects/<nome>/popups.json, separati da timeline.json (che resta del motore):
- "auto": proposti da autocut (es. le immagini AI già generate nel punto in cui sono state chieste);
- "ai":   proposti da Claude analizzando il parlato, o modificati via chat nell'editor;
- "user": aggiunti o cambiati a mano.
Ogni pop-up ha uno stato: proposed (proposta, già visibile nell'anteprima e nel render),
approved, rejected (non compare). Il render usa tutto tranne i rifiutati.

I tempi sono ms sull'asse della camera (come timeline.json), così restano validi anche se
cambiano i tagli: se il punto finisce in una parte tolta, il pop-up semplicemente non si vede.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

POPUPS_FILE = "popups.json"
POPUPS_VERSION = 1

Kind = Literal["image", "emoji", "text"]
Status = Literal["proposed", "approved", "rejected"]
Origin = Literal["auto", "ai", "user"]
# Dove compare (dai reference): accanto al sottotitolo, sopra il testo, una coppia ai due lati,
# grande al centro sotto il testo, in alto sopra la testa, DIETRO la persona (solo premium).
# "free" = messo a mano nel pannello Sticker: centro in x_pct/y_pct (% del fotogramma).
Placement = Literal["side", "above", "pair", "center", "top", "behind", "free"]
Size = Literal["small", "medium", "large"]
PLACEMENTS = ("side", "above", "pair", "center", "top", "behind", "free")
# Livello: dietro ai sottotitoli, davanti ai sottotitoli, o dietro la persona (sagoma).
Layer = Literal["under_text", "over_text", "person"]


class Popup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^pop_\d{4,}$")
    at_ms: int = Field(ge=0)
    duration_ms: int = Field(default=2200, ge=400, le=10000)
    kind: Kind
    title: str = Field(default="", max_length=40)  # etichetta breve (anche vuota)
    emoji: str | None = Field(default=None, max_length=16)
    image: str | None = None  # percorso relativo a work/ (es. ai/results/ai_0001-1.png)
    cutout: bool = False  # foto scontornata (pannello Immagini): senza cornice né sfondo
    image_prompt: str | None = Field(default=None, max_length=1200)  # da generare con Higgsfield
    ai_request: str | None = None  # id della richiesta Higgsfield che genera l'immagine
    sound: bool = True
    status: Status = "proposed"
    origin: Origin = "user"
    reason: str = Field(default="", max_length=300)
    placement: Placement = "side"
    size: Size = "medium"
    side: Literal["left", "right"] = "left"
    style: str | None = None  # stile per cui è stato proposto (None = vale per tutti)
    x_pct: float | None = Field(default=None, ge=0, le=100)  # centro, solo con placement "free"
    y_pct: float | None = Field(default=None, ge=0, le=100)
    scale: float = Field(default=1.0, ge=0.2, le=5.0)  # rispetto alla grandezza di `size`
    rotation: float = Field(default=0.0, ge=-180, le=180)
    layer: Layer = "under_text"
    updated_at: str = ""

    @model_validator(mode="after")
    def _content(self) -> Popup:
        if self.kind == "emoji" and not self.emoji:
            raise ValueError("un pop-up emoji ha bisogno dell'emoji")
        if self.kind == "text" and not self.title:
            raise ValueError("un pop-up di testo ha bisogno del testo")
        if self.kind == "image" and not (self.image or self.image_prompt or self.ai_request):
            raise ValueError("un pop-up immagine ha bisogno di un'immagine o di un prompt")
        if self.placement == "pair" and self.kind != "emoji":
            raise ValueError("la coppia ai lati vuole due emoji (kind emoji)")
        if self.placement == "free" and (self.x_pct is None or self.y_pct is None):
            raise ValueError("uno sticker libero ha bisogno della posizione (x_pct, y_pct)")
        return self

    @property
    def behind_person(self) -> bool:
        return self.placement == "behind" or self.layer == "person"

    def visible_for(self, style_id: str | None) -> bool:
        return self.style is None or self.style == style_id


class PopupsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = POPUPS_VERSION
    items: list[Popup] = Field(default_factory=list)
    seeded: bool = False  # vecchio formato (una sola copia per tutti gli stili)
    seeded_styles: list[str] = Field(default_factory=list)  # stili con le proposte automatiche
    suggested: list[str] = Field(default_factory=list)  # stili già analizzati da Claude


class PopupError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def path_for(project_dir: Path) -> Path:
    return project_dir / POPUPS_FILE


def load(project_dir: Path) -> PopupsFile:
    p = path_for(project_dir)
    if not p.exists():
        return PopupsFile()
    try:
        return PopupsFile.model_validate_json(p.read_bytes())
    except ValidationError as exc:
        raise PopupError(f"{p}: {exc}") from exc


def save(project_dir: Path, data: PopupsFile) -> None:
    p = path_for(project_dir)
    tmp = p.with_suffix(".partial")
    body = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def next_id(data: PopupsFile) -> str:
    nums = [int(x.id.split("_")[1]) for x in data.items]
    return f"pop_{(max(nums) + 1 if nums else 1):04d}"


def sorted_items(data: PopupsFile) -> list[Popup]:
    return sorted(data.items, key=lambda x: (x.at_ms, x.id))


def seed_from_ai_requests(
    data: PopupsFile, project_dir: Path, style: str | None = None
) -> PopupsFile:
    """La prima volta per ogni stile: ogni immagine AI già generata diventa un pop-up proposto
    nel punto in cui è stata chiesta. Una copia per stile, così cambiarla per il premium non
    cambia il viral (e se la cancelli non torna)."""
    key = style or ""
    if key in data.seeded_styles:
        return data
    req_path = project_dir / "ai_requests.json"
    items = list(data.items)
    if req_path.exists():
        for req in json.loads(req_path.read_text(encoding="utf-8")).get("requests", []):
            res = req.get("result") or {}
            if req.get("status") != "done" or res.get("media_type") != "image":
                continue
            local = res.get("local") or []
            # già presente per questo stile, o generata apposta per un pop-up preciso
            if not local or any(
                x.ai_request == req["id"] and (x.style == style or x.origin != "auto")
                for x in items
            ):
                continue
            name = local[0].rsplit("/", 1)[-1]
            items.append(
                Popup(
                    id=next_id(PopupsFile(items=items)),
                    at_ms=int(req["time_ms"]),
                    kind="image",
                    image=f"ai/results/{name}",
                    ai_request=req["id"],
                    origin="auto",
                    reason="immagine AI generata per questo punto",
                    style=style,
                    updated_at=_now(),
                )
            )
    return data.model_copy(update={"items": items, "seeded_styles": [*data.seeded_styles, key]})


EDITABLE = {
    "at_ms", "duration_ms", "kind", "title", "emoji", "image", "image_prompt", "sound", "status",
    "reason", "ai_request", "placement", "size", "side", "style",
    "x_pct", "y_pct", "scale", "rotation", "layer", "cutout",
}  # fmt: skip

# Libreria del pannello Sticker, per stile (le immagini AI del progetto si aggiungono a parte).
STICKERS: dict[str, dict[str, list[str]]] = {
    "viral": {
        # le più usate della tastiera del telefono (WhatsApp / CapCut)
        "emoji": ["😂", "❤️", "😍", "🔥", "😭", "🙏", "😱", "🤯", "😎", "🥳", "🤔", "😅", "👏",
                  "💪", "👀", "💯", "✅", "❌", "👇", "💰", "💸", "🤑", "🚀", "🏆", "🇮🇹"],
        "text": ["WOW", "BOOM", "TOP", "NO!", "SÌ!", "+100%", "GRATIS", "ATTENZIONE"],
    },
    "premium": {
        "emoji": ["📈", "💼", "🏆", "✨", "🎯", "🔑", "📊", "💎", "🌍", "⏱️"],
        "text": ["60s", "+40%", "2026", "TOP 1%", "€10K", "x10", "100%", "#1"],
    },
}  # fmt: skip


def apply_ops(
    data: PopupsFile,
    ops: dict[str, Any],
    origin: Origin,
    *,
    words: dict[str, int] | None = None,
    style: str | None = None,
    min_gap_ms: int = 0,
    max_count: int | None = None,
) -> tuple[PopupsFile, list[str]]:
    """Applica {"add": [...], "update": [{"id":..., campi}], "remove": [ids]}.

    Per aggiungere si può dare `word_id` (l'inizio di quella parola) invece di `at_ms`.
    `style`: i nuovi pop-up valgono solo per quello stile. `min_gap_ms` / `max_count`:
    parsimonia — un'aggiunta troppo vicina a un altro pop-up dello stesso stile, o oltre il
    numero massimo, viene scartata (meglio un video pulito che pieno).
    Restituisce il nuovo file e un elenco leggibile di cosa è cambiato.
    """
    items = {x.id: x for x in data.items}
    log: list[str] = []
    words = words or {}

    for rid in ops.get("remove", []) or []:
        if items.pop(str(rid), None) is not None:
            log.append(f"tolto {rid}")
    for upd in ops.get("update", []) or []:
        pid = str(upd.get("id", ""))
        cur = items.get(pid)
        if cur is None:
            raise PopupError(f"pop-up {pid!r} non trovato")
        fields = {k: v for k, v in upd.items() if k in EDITABLE}
        if "word_id" in upd and upd["word_id"] in words:
            fields["at_ms"] = words[upd["word_id"]]
        try:
            items[pid] = Popup.model_validate(
                {**cur.model_dump(), **fields, "origin": origin, "updated_at": _now()}
            )
        except ValidationError as exc:
            raise PopupError(f"{pid}: {exc.errors()[0]['msg']}") from exc
        log.append(f"cambiato {pid}")
    for add in ops.get("add", []) or []:
        fields = {k: v for k, v in add.items() if k in EDITABLE}
        if "at_ms" not in fields:
            wid = add.get("word_id")
            if wid not in words:
                raise PopupError(f"pop-up senza tempo valido (word_id {wid!r} sconosciuta)")
            fields["at_ms"] = words[wid]
        fields.setdefault("style", style)
        live = [
            x for x in items.values() if x.status != "rejected" and x.visible_for(fields["style"])
        ]
        if max_count is not None and len(live) >= max_count:
            log.append(f"saltato a {fields['at_ms'] / 1000:.1f}s (già {max_count} pop-up)")
            continue
        if min_gap_ms and any(abs(x.at_ms - int(fields["at_ms"])) < min_gap_ms for x in live):
            log.append(f"saltato a {fields['at_ms'] / 1000:.1f}s (troppo vicino a un altro)")
            continue
        new_id = next_id(PopupsFile(items=list(items.values())))
        try:
            items[new_id] = Popup.model_validate(
                {
                    "status": "proposed",
                    **fields,
                    "id": new_id,
                    "origin": origin,
                    "updated_at": _now(),
                }
            )
        except ValidationError as exc:
            raise PopupError(f"nuovo pop-up: {exc.errors()[0]['msg']}") from exc
        log.append(f"aggiunto {new_id}")
    return data.model_copy(update={"items": list(items.values())}), log


# --- prompt per Claude -----------------------------------------------------------------

# Parsimonia: un pop-up ogni N secondi al massimo, e distanza minima tra due pop-up.
LIMITS = {"premium": (18.0, 8000), "viral": (10.0, 4500)}  # (secondi per pop-up, distanza ms)


def limits(style_id: str | None, duration_ms: int) -> tuple[int, int]:
    """(numero massimo di pop-up, distanza minima in ms) per lo stile e la durata del video."""
    per, gap = LIMITS.get(style_id or "", LIMITS["premium"])
    return max(1, round(duration_ms / 1000 / per)), gap


STYLE_LOGIC = {
    "premium": (
        "Logica PREMIUM (elegante, costoso, alla Belfort): pochissimi pop-up, solo sui concetti più "
        "forti (un luogo, un numero, un risultato, un oggetto concreto). Niente emoji, niente meme.\n"
        "Posizioni da usare:\n"
        "- behind: GRANDE, DIETRO la persona (passa dietro la testa/le spalle). Per oggetti "
        "iconici (contratto che vola, sacco di soldi, mappamondo: kind image con image_prompt di un "
        "oggetto 3D isolato su sfondo neutro) o per un numero/parola enorme (kind text, es. «60s», "
        "«25»). Usala solo quando è davvero d'effetto, al massimo 1-2 volte nel video.\n"
        "- side: card di vetro media di lato (kind image) per mostrare un luogo/una cosa reale.\n"
        "- top: oggetto o immagine in alto sopra la testa, davanti (se behind non serve)."
    ),
    "viral": (
        "Logica VIRAL (CapCut, provinciale, alla CRABBOX): divertente e immediato, ma con parsimonia: "
        "non a ogni frase, solo dove la parola si presta. Etichette brevi MAIUSCOLE.\n"
        "Posizioni da usare, variando:\n"
        "- side: emoji PICCOLA accanto al sottotitolo (es. 💪 su «carattere»), side left/right.\n"
        "- above: emoji PICCOLA sopra il testo (es. 🏠 su «casa», 😡 sopra un hook arrabbiato).\n"
        "- pair: DUE emoji ai due lati del sottotitolo quando si nominano due cose (es. «🇨🇳🇺🇸» "
        "per «Asia e America»): kind emoji con le due emoji una dopo l'altra in emoji.\n"
        "- center: GRANDE al centro sotto il testo, per il momento clou (una bandiera, un piatto, "
        "un luogo): kind image (image_prompt) o una emoji grande. Al massimo 1-2 nel video.\n"
        "Le bandiere emoji vanno bene (vengono disegnate con il font Noto Color Emoji)."
    ),
}
# Regole comuni.
COMMON_RULES = (
    "Regole: pochi e giusti, il video pulito vale di più. Mai un pop-up per frase, mai due di fila "
    "sulla stessa idea. Compaiono quando viene detta la parola (word_id) e restano 1,5-2,5 s. "
    "Scegli la grandezza in base all'importanza: small per un dettaglio, medium per un elemento da "
    "mostrare, large solo per il momento più forte. Il suono (sound true) solo sui momenti davvero "
    "importanti (un concetto forte, un elemento da far notare); sugli altri sound false."
)


def transcript_block(words: list[tuple[str, str, int]]) -> str:
    """Righe 'w000012 @ 39.50s  Thailandia' (id parola, tempo, testo)."""
    return "\n".join(f"{wid} @ {ms / 1000:.2f}s  {text}" for wid, text, ms in words)


def _existing_block(data: PopupsFile, style_id: str | None) -> str:
    rows = []
    for x in sorted_items(data):
        if not x.visible_for(style_id):
            continue
        what = x.emoji or x.image or x.image_prompt or ""
        rows.append(
            f"{x.id} @ {x.at_ms / 1000:.2f}s {x.kind} {x.placement}/{x.size} «{x.title}» "
            f"{what[:60]} [{x.status}, {x.origin}]"
        )
    return "\n".join(rows) or "(nessuno)"


_OPS_SCHEMA = """{"add": [{"word_id": "w000123", "duration_ms": 2000, "kind": "image|emoji|text",
  "placement": "side|above|pair|center|top|behind", "size": "small|medium|large",
  "side": "left|right", "title": "max 3 parole (anche vuoto)", "emoji": "solo per kind emoji",
  "image_prompt": "solo per kind image: prompt in inglese, ultra realistico, senza testo",
  "sound": false, "reason": "perché qui, 1 frase"}],
 "update": [{"id": "pop_0001", "...campi da cambiare...": "..."}],
 "remove": ["pop_0002"],
 "message": "cosa hai fatto, 1-2 frasi in italiano"}"""


def _header(
    style_id: str | None, style_name: str, budget: tuple[int, int], duration_ms: int
) -> str:
    logic = STYLE_LOGIC.get(style_id or "", STYLE_LOGIC["premium"])
    count, gap = budget
    return (
        "Sei il motion designer di un editor video per i social (video verticale 9:16).\n"
        f"Stile scelto: «{style_name}».\n{logic}\n{COMMON_RULES}\n"
        f"Il video dura {duration_ms / 1000:.0f} s: AL MASSIMO {count} pop-up in tutto (contando "
        f"quelli presenti), almeno {gap / 1000:.1f} s tra uno e l'altro. Meno va benissimo."
    )


def suggest_prompt(
    *,
    style_id: str | None,
    style_name: str,
    words: list[tuple[str, str, int]],
    data: PopupsFile,
    duration_ms: int = 60000,
) -> str:
    budget = limits(style_id, duration_ms)
    return f"""{_header(style_id, style_name, budget, duration_ms)}

Trascrizione con id e tempo di ogni parola:
{transcript_block(words)}

Pop-up già presenti per questo stile:
{_existing_block(data, style_id)}

Analizza il parlato e proponi solo i pop-up che servono davvero (puoi anche cambiare posizione o
grandezza di quelli presenti, o proporre di toglierli se sono deboli).

Rispondi SOLO con questo JSON, senza altro testo:
{_OPS_SCHEMA}"""


def chat_prompt(
    *,
    style_id: str | None,
    style_name: str,
    words: list[tuple[str, str, int]],
    data: PopupsFile,
    request: str,
    time_ms: int,
    duration_ms: int = 60000,
) -> str:
    budget = limits(style_id, duration_ms)
    return f"""{_header(style_id, style_name, budget, duration_ms)}

Il creator è fermo a {time_ms / 1000:.2f}s e ti chiede: «{request}»

Trascrizione con id e tempo di ogni parola:
{transcript_block(words)}

Pop-up attuali per questo stile:
{_existing_block(data, style_id)}

Fai SOLO quello che chiede (aggiungere, cambiare o togliere pop-up, anche posizione e grandezza),
con la logica dello stile. "Questo", "qui", "quello" si riferiscono al pop-up o alla parola più
vicini a {time_ms / 1000:.2f}s. Se chiede di aggiungerne uno puoi superare il limite.
Per cambiare un'immagine metti un nuovo image_prompt (verrà generata solo quando il creator lo conferma).

Rispondi SOLO con questo JSON, senza altro testo:
{_OPS_SCHEMA}"""
