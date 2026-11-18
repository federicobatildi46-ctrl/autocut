"""Musica di sottofondo dalla libreria gratuita del canale YouTube «Audio Library» (@audiolibrary_).

Ogni brano del canale è gratuito anche per video monetizzati, a patto di mettere in descrizione
i crediti che il canale indica (artista, licenza, link): l'editor li conserva per ogni brano e
te li dà pronti da copiare. I titoli descrivono già mood, genere e uso («Emotional Cinematic
Music for Documentaries | Scott Buckley - First Snow») e la descrizione ha le sezioni del brano
(«0:30 Heavy bass momentum»): Claude sceglie così il brano e anche il punto da cui farlo partire.

- Catalogo: titoli di tutti i video del canale (yt-dlp, veloce), in library/music/catalog.json.
- Scelta: (1) Claude legge il parlato e lo stile e dice il mood; (2) dai titoli più vicini sceglie
  5 brani; (3) dalle sezioni di ognuno sceglie da dove partire. I 5 vengono scaricati subito
  (ascolto veloce nell'editor). Tutto in locale, nessun credito.
- Nel video: music.json del progetto, una o più voci sul raw (tutto il video o solo un tratto),
  con volume relativo alla voce (`music_db` dello stile), muto, dissolvenze, punto di partenza.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .paths import REPO_ROOT

CHANNEL = "https://www.youtube.com/@audiolibrary_/videos"
MUSIC_DIR = REPO_ROOT / "library" / "music"  # condivisa fra i progetti (fuori da git)
MUSIC_FILE = "music.json"
CATALOG_MAX_AGE_DAYS = 7
CANDIDATES = 5
SHORTLIST = 40
_CA = Path.home() / ".config" / "watch" / "windows-ca.pem"  # TLS intercettato su questo PC

Runner = Callable[[list[str], int], str]


class MusicError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --- yt-dlp -------------------------------------------------------------------------------


def ytdlp(args: list[str], timeout: int = 600) -> str:
    exe = shutil.which("yt-dlp")
    if exe is None:
        raise MusicError("yt-dlp non trovato: winget install yt-dlp")
    env = dict(os.environ)
    if _CA.exists():
        env.setdefault("CURL_CA_BUNDLE", str(_CA))
    try:
        proc = subprocess.run(
            # certificati di Windows anche senza il config.txt di yt-dlp (TLS intercettato)
            [exe, "--compat-options", "no-certifi", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise MusicError("YouTube non ha risposto in tempo") from exc
    if proc.returncode != 0:
        raise MusicError(f"yt-dlp: {(proc.stderr or proc.stdout).strip()[-300:]}")
    return proc.stdout


# --- titoli, descrizioni e catalogo ---------------------------------------------------------


def parse_title(title: str) -> dict[str, str]:
    """«Mood Genere for Usi (No Copyright) | Artista - Brano» -> campi separati."""
    left, _, right = title.rpartition(" | ")
    if not left:
        left, right = title, ""
    left = re.sub(r"\s*\((?:No Copyright|Royalty Free|Free to Use|Free)[^)]*\)\s*$", "",
                  left.strip(), flags=re.I)  # fmt: skip
    mood, _, uses = left.partition(" for ")
    artist, _, song = right.partition(" - ")
    return {"mood": mood.strip(), "uses": uses.strip(), "artist": artist.strip(),
            "song": song.strip() or right.strip()}  # fmt: skip


def parse_description(desc: str) -> dict[str, Any]:
    """Crediti da copiare in descrizione e sezioni del brano (TRACK BREAKDOWN)."""
    credits = []
    for line in desc.splitlines():
        s = line.strip()
        if re.match(
            r"^(Music|License|Free Download / Stream|Music promoted by Audio Library)\s*:", s
        ):
            credits.append(s)
    breakdown = []
    on = False
    for line in desc.splitlines():
        s = line.strip()
        if "TRACK BREAKDOWN" in s.upper():
            on = True
            continue
        if on:
            m = re.match(r"^(\d{1,2}):(\d{2})\s+(.+)$", s)
            if m:
                breakdown.append({"at_s": int(m[1]) * 60 + int(m[2]), "text": m[3][:120]})
            elif breakdown and s.startswith("*"):
                break
    license_ = next((c.split(":", 1)[1].strip() for c in credits if c.startswith("License")), "")
    summary = desc.strip().split("\n\n")[0][:300] if desc.strip() else ""
    return {"credits": "\n".join(credits), "license": license_, "breakdown": breakdown,
            "summary": summary}  # fmt: skip


def load_catalog(root: Path = MUSIC_DIR) -> dict[str, Any]:
    p = root / "catalog.json"
    if not p.exists():
        return {"updated_at": None, "tracks": []}
    return json.loads(p.read_text(encoding="utf-8"))


def refresh_catalog(
    root: Path = MUSIC_DIR, run: Runner = ytdlp, force: bool = False
) -> dict[str, Any]:
    """Titoli di tutti i video del canale (una volta a settimana; ~1 minuto)."""
    cat = load_catalog(root)
    if cat["tracks"] and not force and cat.get("updated_at"):
        age = datetime.now().astimezone() - datetime.fromisoformat(cat["updated_at"])
        if age.days < CATALOG_MAX_AGE_DAYS:
            return cat
    out = run(["--flat-playlist", "--print", "%(id)s|%(duration)s|%(title)s", CHANNEL], 900)
    tracks = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3 or not re.fullmatch(r"[\w-]{11}", parts[0]):
            continue
        try:
            dur = int(float(parts[1]))
        except ValueError:
            dur = 0
        tracks.append(
            {"id": parts[0], "duration_s": dur, "title": parts[2], **parse_title(parts[2])}
        )
    if not tracks:
        raise MusicError("il canale Audio Library non ha restituito brani")
    cat = {"updated_at": _now(), "source": CHANNEL, "tracks": tracks}
    root.mkdir(parents=True, exist_ok=True)
    (root / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    return cat


def search(cat: dict[str, Any], words: list[str], limit: int = SHORTLIST,
           min_s: int = 45) -> list[dict[str, Any]]:  # fmt: skip
    """Brani i cui titoli contengono più parole chiave (mood/genere/uso), i più lunghi a parità."""
    keys = [w.lower().strip() for w in words if w and w.strip()]
    scored = []
    for t in cat["tracks"]:
        text = f"{t['mood']} {t['uses']}".lower()
        score = sum(2 if k in t["mood"].lower() else 1 for k in keys if k in text)
        if score and t.get("duration_s", 0) >= min_s:
            scored.append((score, t.get("duration_s", 0), t))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [t for _, _, t in scored[:limit]]


# --- un brano: dettagli, download, loudness ------------------------------------------------


def track_path(track_id: str, root: Path = MUSIC_DIR) -> Path:
    return root / "files" / f"{track_id}.m4a"


def track_meta(track_id: str, root: Path = MUSIC_DIR, run: Runner = ytdlp) -> dict[str, Any]:
    """Titolo, crediti, licenza e sezioni del brano (cache in library/music/tracks/)."""
    if not re.fullmatch(r"[\w-]{11}", track_id):
        raise MusicError(f"id brano non valido: {track_id}")
    p = root / "tracks" / f"{track_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    raw = run(
        ["--skip-download", "--dump-single-json", f"https://www.youtube.com/watch?v={track_id}"],
        120,
    )
    info = json.loads(raw)
    title = info.get("title", "")
    meta = {"id": track_id, "title": title, "duration_s": int(info.get("duration") or 0),
            "url": f"https://www.youtube.com/watch?v={track_id}", **parse_title(title),
            **parse_description(info.get("description") or "")}  # fmt: skip
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def download(track_id: str, root: Path = MUSIC_DIR, run: Runner = ytdlp,
             lufs: Callable[[Path], float | None] | None = None) -> dict[str, Any]:  # fmt: skip
    """Scarica l'audio del brano (m4a) e ne misura la loudness, una volta sola."""
    meta = track_meta(track_id, root, run)
    dest = track_path(track_id, root)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a", "--no-playlist",
             "-o", str(dest.with_suffix(".%(ext)s")), meta["url"]], 600)  # fmt: skip
        if not dest.exists():
            raise MusicError(f"download non riuscito: {meta.get('song') or track_id}")
    if meta.get("lufs") is None:
        if lufs is None:
            from .render.preview import measure_lufs

            lufs = measure_lufs
        meta["lufs"] = lufs(dest)
        (root / "tracks" / f"{track_id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return meta


# --- il progetto: music.json ----------------------------------------------------------------


class MusicItem(BaseModel):
    id: str = Field(pattern=r"^mus_\d{4,}$")
    track: str = Field(pattern=r"^[\w-]{11}$")
    start_ms: int | None = Field(default=None, ge=0)  # raw; None = dall'inizio del video
    end_ms: int | None = Field(default=None, ge=0)  # raw; None = fino alla fine
    offset_ms: int = Field(default=0, ge=0)  # punto del brano da cui parte
    gain_db: float = Field(default=0.0, ge=-30, le=12)  # rispetto al livello dello stile
    muted: bool = False
    fade_in_ms: int = Field(default=800, ge=0, le=10000)
    fade_out_ms: int = Field(default=1500, ge=0, le=10000)
    style: str | None = None  # stile per cui è stata messa (None = tutti)
    origin: Literal["ai", "user"] = "user"
    why: str = Field(default="", max_length=400)


class Candidate(BaseModel):
    id: str
    why: str = ""
    offset_ms: int = 0
    section: str = ""


class Suggestion(BaseModel):
    vibe: str = ""
    start_ms: int | None = None
    end_ms: int | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    created_at: str = ""


class MusicFile(BaseModel):
    version: int = 1
    items: list[MusicItem] = Field(default_factory=list)
    suggestions: dict[str, Suggestion] = Field(default_factory=dict)  # per stile ("" = nessuno)
    auto_done: list[str] = Field(default_factory=list)  # stili già passati dal premontaggio


def load(project_dir: Path) -> MusicFile:
    p = project_dir / MUSIC_FILE
    if not p.exists():
        return MusicFile()
    return MusicFile.model_validate_json(p.read_text(encoding="utf-8"))


def save(project_dir: Path, data: MusicFile) -> None:
    p = project_dir / MUSIC_FILE
    tmp = p.with_suffix(".partial")
    tmp.write_text(data.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def visible(item: MusicItem, style: str | None) -> bool:
    return item.style is None or item.style == style


def add_item(data: MusicFile, **fields: Any) -> tuple[MusicFile, MusicItem]:
    n = max((int(i.id.split("_")[1]) for i in data.items), default=0) + 1
    item = MusicItem(id=f"mus_{n:04d}", **fields)
    if item.start_ms is not None and item.end_ms is not None and item.end_ms <= item.start_ms:
        raise MusicError("il tratto della musica è vuoto: la fine deve venire dopo l'inizio")
    return data.model_copy(update={"items": [*data.items, item]}), item


EDITABLE = {"start_ms", "end_ms", "offset_ms", "gain_db", "muted", "fade_in_ms", "fade_out_ms",
            "track", "style"}  # fmt: skip


def update_item(data: MusicFile, item_id: str, fields: dict[str, Any]) -> MusicFile:
    bad = set(fields) - EDITABLE
    if bad:
        raise MusicError(f"campi non modificabili: {', '.join(sorted(bad))}")
    items = []
    found = False
    for i in data.items:
        if i.id == item_id:
            i = MusicItem(**{**i.model_dump(), **fields})
            found = True
        items.append(i)
    if not found:
        raise MusicError(f"musica {item_id} non trovata")
    return data.model_copy(update={"items": items})


def remove_item(data: MusicFile, item_id: str) -> MusicFile:
    if not any(i.id == item_id for i in data.items):
        raise MusicError(f"musica {item_id} non trovata")
    return data.model_copy(update={"items": [i for i in data.items if i.id != item_id]})


def level_db(meta: dict[str, Any], style_sound: dict[str, Any], gain_db: float) -> float:
    """Guadagno da dare al file: la musica sta `music_db` sotto la voce normalizzata."""
    target = style_sound.get("voice_lufs", -14.0) + style_sound.get("music_db", -19.0) + gain_db
    measured = meta.get("lufs")
    return round(target - (measured if measured is not None else -14.0), 2)


# --- scelta con Claude ------------------------------------------------------------------------


def mood_prompt(context: str, style: str | None, seconds: float, note: str = "") -> str:
    return f"""Sei il music supervisor di un creator italiano di video social.
Stile di montaggio: {style or "nessuno"} (viral = veloce, dinamico; premium = pulito, elegante).
Durata da coprire: circa {seconds:.0f} s. {f"Richiesta del creator: «{note}»." if note else ""}
Cosa dice il creator (con il contesto del video):
{context[:6000]}

Decidi il mood della musica di sottofondo: deve accompagnare il parlato senza coprirlo e senza
distrarre (niente brani natalizi, comici o troppo drammatici se il tono non lo chiede).
Le parole chiave servono a cercare fra titoli in INGLESE del tipo «Chill Lo-fi Beats for Vlogs»,
«Hopeful Cinematic Music for Motivational Videos», «Powerful House Music for Car Videos»:
usa parole di mood, genere e uso (es. "motivational", "upbeat", "lo-fi", "cinematic", "corporate",
"inspiring", "chill", "tech", "vlog", "business", "dark", "energetic").

Rispondi SOLO con:
{{"vibe": "il mood in italiano, una frase", "energy": "low|medium|high",
"keywords": ["8-14 parole chiave in inglese, minuscole"]}}"""


def pick_prompt(vibe: str, energy: str, style: str | None, shortlist: list[dict[str, Any]]) -> str:
    rows = "\n".join(f"{t['id']} | {t['duration_s']} s | {t['mood']} for {t['uses']} | {t['artist']}"
                     for t in shortlist)  # fmt: skip
    return f"""Scegli la musica di sottofondo per un video social ({style or "senza stile"}).
Mood cercato: {vibe} (energia {energy}).
Brani disponibili (libreria gratuita Audio Library, id | durata | descrizione | artista):
{rows}

Scegli i {CANDIDATES} brani migliori, dal più adatto, vari fra loro (non 5 uguali). Sotto il
parlato funzionano meglio brani strumentali, regolari, senza cambi bruschi.
Rispondi SOLO con: {{"picks": [{{"id": "...", "why": "perché, in italiano, breve"}}]}}"""


def section_prompt(vibe: str, energy: str, seconds: float, tracks: list[dict[str, Any]]) -> str:
    blocks = []
    for t in tracks:
        secs = "; ".join(
            f"{b['at_s'] // 60}:{b['at_s'] % 60:02d} {b['text']}" for b in t.get("breakdown", [])
        )
        blocks.append(
            f"- {t['id']} «{t.get('song')}» ({t.get('duration_s')} s): {secs or 'nessuna sezione indicata'}"
        )
    lines = "\n".join(blocks)
    return f"""Per ognuno di questi brani scegli da quale secondo farlo partire sotto un video di
circa {seconds:.0f} s con mood «{vibe}» (energia {energy}). Usa le sezioni indicate: parti da
quella che ha già l'energia giusta (non da un intro lungo e vuoto), lasciando se possibile
abbastanza brano dopo per coprire il video.
{lines}

Rispondi SOLO con: {{"sections": [{{"id": "...", "start_s": 0, "section": "nome breve"}}]}}"""


def suggest(
    *,
    ask: Callable[[str], dict[str, Any]],
    context: str,
    style: str | None,
    seconds: float,
    note: str = "",
    root: Path = MUSIC_DIR,
    run: Runner = ytdlp,
    lufs: Callable[[Path], float | None] | None = None,
    progress: Callable[[str], None] = lambda s: None,
) -> tuple[str, list[Candidate]]:
    """Mood -> 5 brani -> sezione di partenza; i 5 brani vengono scaricati subito."""
    progress("aggiorno il catalogo Audio Library")
    cat = refresh_catalog(root, run)
    progress("Claude sceglie il mood")
    mood = ask(mood_prompt(context, style, seconds, note))
    vibe = str(mood.get("vibe", ""))[:200]
    energy = str(mood.get("energy", "medium"))
    words = [str(w) for w in (mood.get("keywords") or [])][:16]
    shortlist = search(cat, words, min_s=min(90, max(30, int(seconds * 0.5))))
    if len(shortlist) < CANDIDATES:  # parole troppo strette: si allarga
        shortlist += [
            t for t in search(cat, ["background", "vlog", "chill", "upbeat"]) if t not in shortlist
        ]
    if not shortlist:
        raise MusicError("nessun brano adatto nel catalogo")
    progress("Claude sceglie i brani")
    picks = ask(pick_prompt(vibe, energy, style, shortlist[:SHORTLIST])).get("picks") or []
    known = {t["id"] for t in shortlist}
    chosen = [p for p in picks if isinstance(p, dict) and p.get("id") in known][:CANDIDATES]
    if not chosen:
        chosen = [
            {"id": t["id"], "why": "vicino al mood richiesto"} for t in shortlist[:CANDIDATES]
        ]
    metas = []
    for i, p in enumerate(chosen, 1):
        progress(f"scarico il brano {i} di {len(chosen)}")
        try:
            metas.append(download(p["id"], root, run, lufs))
        except MusicError:
            continue  # un brano che non si scarica si salta
    if not metas:
        raise MusicError("nessun brano scaricato")
    progress("Claude sceglie da dove far partire i brani")
    try:
        secs = {s.get("id"): s for s in ask(section_prompt(vibe, energy, seconds, metas)).get("sections") or []
                if isinstance(s, dict)}  # fmt: skip
    except Exception:  # noqa: BLE001 - senza sezione si parte dall'inizio
        secs = {}
    why = {p["id"]: str(p.get("why", ""))[:300] for p in chosen}
    out = []
    for m in metas:
        s = secs.get(m["id"], {})
        start = max(0, min(int(float(s.get("start_s") or 0)), max(0, m.get("duration_s", 0) - 10)))
        out.append(Candidate(id=m["id"], why=why.get(m["id"], ""), offset_ms=start * 1000,
                             section=str(s.get("section", ""))[:80]))  # fmt: skip
    return vibe, out


# --- render ----------------------------------------------------------------------------------


def render_music(
    project_dir: Path, work: Path, to_out: Callable[..., int | None], pieces: list[Any],
    style: str | None, style_sound: dict[str, Any], root: Path = MUSIC_DIR,
) -> list[dict[str, Any]]:  # fmt: skip
    """Musica per Remotion: tratti sul montato, file nella cartella pubblica, volume e fade."""
    if not pieces:
        return []
    out_end = max(p.out_end for p in pieces)
    out = []
    for it in load(project_dir).items:
        if it.muted or not visible(it, style):
            continue
        src = track_path(it.track, root)
        if not src.exists():
            continue
        meta = track_meta(it.track, root)

        def at(ms: int | None, first: bool) -> int | None:
            if ms is None:
                return 0 if first else out_end
            v = to_out(pieces, ms)
            if v is not None:
                return v
            if first:  # il punto cade in una parte tolta: dal primo tratto dopo
                return next((p.out_start for p in pieces if p.src_start >= ms), None)
            return next((p.out_end for p in reversed(pieces) if p.src_end <= ms), None)

        a, b = at(it.start_ms, True), at(it.end_ms, False)
        if a is None or b is None or b - a < 300:
            continue
        dest = work / "render" / "music" / src.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        db = level_db(meta, style_sound, it.gain_db)
        out.append({
            "id": it.id, "src": f"render/music/{src.name}", "from_ms": int(a), "dur_ms": int(b - a),
            "offset_ms": it.offset_ms, "volume": round(min(1.0, math.pow(10, db / 20)), 4),
            "fade_in_ms": it.fade_in_ms, "fade_out_ms": it.fade_out_ms,
            "loop": (meta.get("duration_s") or 0) * 1000 - it.offset_ms < (b - a),
        })  # fmt: skip
    return out


def credits_text(project_dir: Path, style: str | None, root: Path = MUSIC_DIR) -> str:
    """Crediti da incollare nella descrizione del video (licenza dei brani usati)."""
    seen, blocks = set(), []
    for it in load(project_dir).items:
        if it.muted or not visible(it, style) or it.track in seen:
            continue
        seen.add(it.track)
        p = root / "tracks" / f"{it.track}.json"
        if p.exists():
            meta = json.loads(p.read_text(encoding="utf-8"))
            if meta.get("credits"):
                blocks.append(meta["credits"])
    return "\n\n".join(blocks)
