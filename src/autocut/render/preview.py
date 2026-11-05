"""Anteprima di uno stile su un pezzetto del video vero, renderizzata con Remotion.

Prende una finestra di pochi secondi attorno a un istante, applica i tagli effettivi
(proposte + override), il look brand × stile, i sottotitoli, l'hook, le card con le immagini AI
già generate e i suoni della libreria; poi chiede a Remotion un fotogramma (PNG) o la clip (MP4).
Il raw è solo letto: la sorgente del render è un estratto H.264 in work/render/.
Costo: zero crediti (riusa le immagini AI già pagate e i suoni già generati).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import popups as pops
from ..models.timeline import Timeline
from ..overrides.resolve import EffectiveRange
from ..paths import REPO_ROOT
from ..sound.library import LIBRARY_DIR
from .captions import TimedWord, build_chunks, emphasis_index

MOTION_DIR = REPO_ROOT / "motion"
COMPOSITION = "StyledReel"
FPS = 30


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Piece:
    """Tratto tenuto del raw [src_start, src_end) che nel montato inizia a out_start."""

    src_start: int
    src_end: int
    out_start: int

    @property
    def out_end(self) -> int:
        return self.out_start + self.src_end - self.src_start


def pieces_in_window(eff: list[EffectiveRange], start_ms: int, end_ms: int) -> list[Piece]:
    out: list[Piece] = []
    t = 0
    for r in eff:
        if r.state != "keep":
            continue
        a, b = max(r.start_ms, start_ms), min(r.end_ms, end_ms)
        if b - a < 120:  # pezzetti troppo corti: meglio saltarli
            continue
        if out and out[-1].src_end == a:  # tratti contigui: un solo pezzo
            last = out.pop()
            out.append(Piece(last.src_start, b, last.out_start))
            t = out[-1].out_end
            continue
        out.append(Piece(a, b, t))
        t += b - a
    return out


def to_out(pieces: list[Piece], ms: int) -> int | None:
    for p in pieces:
        if p.src_start <= ms < p.src_end:
            return p.out_start + ms - p.src_start
    return None


def _ff(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RenderError(f"{what}: {proc.stderr.decode('utf-8', 'replace').strip()[-400:]}")


_LUFS_RE = re.compile(r"I:\s+(-?\d+(?:\.\d+)?) LUFS")


def measure_lufs(path: Path) -> float | None:
    """Loudness integrata (EBU R128) di un file audio/video, con ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or not path.exists():
        return None
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-map", "0:a:0",
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip
    found = _LUFS_RE.findall(proc.stderr)
    if not found:
        return None
    value = float(found[-1])
    return value if value > -69 else None  # -70 = silenzio o troppo corto per misurare


def sfx_loudness(entry: dict[str, Any], root: Path = LIBRARY_DIR) -> float | None:
    """Loudness di un suono della libreria (misura una volta, poi cache in loudness.json)."""
    cache_path = root / "loudness.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    key = entry["file"]
    if key not in cache:
        value = measure_lufs(root / key)
        if value is None and entry.get("rms_dbfs") is not None:
            value = float(entry["rms_dbfs"])  # ripiego: RMS ~ loudness per suoni brevi
        cache[key] = value
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return cache[key]


def voice_gain_db(work: Path, tl: Timeline, src: Path, target_lufs: float) -> float:
    """Guadagno per portare la voce dell'intero video a `target_lufs` (misura in cache).

    L'iPhone con il Lark registra basso (~-34 LUFS): senza normalizzare, qualunque effetto
    sembra fortissimo. Si misura tutto l'audio camera, non solo la finestra, così ogni
    anteprima e il render finale hanno lo stesso livello.
    """
    cache_path = work / "render" / "voice.json"
    fp = tl.sources.camera.fingerprint
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if cache.get("fingerprint") != fp:
        flacs = sorted(work.glob("camera-*.flac"), key=lambda p: p.stat().st_mtime)
        lufs = measure_lufs(flacs[-1] if flacs else src)
        cache = {"fingerprint": fp, "lufs": lufs}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    if cache["lufs"] is None:
        return 0.0
    return round(max(-10.0, min(30.0, target_lufs - cache["lufs"])), 1)


def ensure_source(
    work: Path, tl: Timeline, src: Path, start_ms: int, end_ms: int, gain_db: float = 0.0
) -> Path:
    """Estratto H.264 a piena risoluzione della finestra (cache in work/render/), con la voce
    portata al livello giusto e un limiter a -1 dBTP (niente distorsione)."""
    fp = tl.sources.camera.fingerprint.split(":", 1)[-1][:12]
    dest = work / "render" / f"src-{fp}-{start_ms}-{end_ms}-g{gain_db:+.1f}.mp4"
    if dest.exists():
        return dest
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RenderError("ffmpeg non trovato nel PATH")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".partial.mp4")
    v = tl.sources.camera.video
    portrait = v.display_height >= v.display_width
    scale = "scale=1080:1920" if portrait else "scale=1920:1080"
    _ff(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{start_ms / 1000:.3f}",
            "-to",
            f"{end_ms / 1000:.3f}",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"{scale}:flags=lanczos,format=yuv420p",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "16",
            "-g",
            str(FPS),
            "-af",
            f"volume={gain_db:.1f}dB,alimiter=limit=0.891:level=false",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(tmp),
        ],  # fmt: skip
        "estratto per il render",
    )
    tmp.replace(dest)
    return dest


MATTE_WORKER = Path(__file__).with_name("matte_worker.py")
MATTE_ENV = ["--no-project", "--python", "3.12", "--with", "mediapipe==0.10.14",
             "--with", "opencv-python-headless"]  # fmt: skip


def ensure_masks(source: Path) -> tuple[Path, int]:
    """Maschere della persona (una JPG per fotogramma: bianco = sfondo, nero = persona) per
    le grafiche DIETRO: la grafica si vede solo dove non ci sei tu.

    La sagoma viene da MediaPipe in un ambiente separato (Python 3.12), calcolata in locale.
    Cache accanto all'estratto: si rifà solo se cambia la finestra.
    """
    dest = source.with_name(source.stem + "-mask")
    done = dest / "done.txt"
    if done.exists():
        return dest, int(done.read_text())
    uv = shutil.which("uv")
    if uv is None:
        raise RenderError("per le grafiche dietro la persona serve uv nel PATH")
    proc = subprocess.run(
        [uv, "run", "--system-certs", *MATTE_ENV, "python", str(MATTE_WORKER),
         str(source), str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip
    if proc.returncode != 0 or not done.exists():
        raise RenderError(f"sagoma della persona: {(proc.stderr or proc.stdout).strip()[-500:]}")
    return dest, int(done.read_text())


def _timed_words(tl: Timeline, pieces: list[Piece]) -> list[TimedWord]:
    out = []
    for w in tl.words:
        if w.kind != "word":
            continue
        s = to_out(pieces, w.start_ms)
        if s is None:
            continue
        e = to_out(pieces, max(w.start_ms, w.end_ms - 1))
        out.append(TimedWord(w.text, s, (e + 1) if e is not None else s + 200))
    return out


def _phrase_starts(words: list[TimedWord]) -> list[int]:
    """Inizio di ogni frase (dopo . ? ! o una pausa lunga): lì cambia il punch-in."""
    starts: list[int] = []
    prev: TimedWord | None = None
    for w in words:
        if prev is None or re.search(r"[.?!]$", prev.text) or w.start_ms - prev.end_ms > 700:
            starts.append(w.start_ms)
        prev = w
    return starts


def _catalog() -> dict[str, list[dict[str, Any]]]:
    path = LIBRARY_DIR / "catalog.json"
    if not path.exists():
        return {}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for s in json.loads(path.read_text(encoding="utf-8"))["sounds"]:
        by_type.setdefault(s["type"], []).append(s)
    return by_type


@dataclass(frozen=True)
class SoundEvent:
    """Un momento che merita un suono: l'istante esatto in cui l'elemento diventa visibile."""

    at_ms: int
    kind: str  # hook | card_in | cut | emphasis | ... (chiavi di sound.events dello stile)
    reason: str


# Se due eventi sono troppo vicini vince il più importante (il suono non deve affollare).
EVENT_PRIORITY = {"hook": 5, "card_in": 4, "block": 3, "cut": 3, "flash": 3, "emphasis": 2}


def _snap(ms: int, fps: int = FPS) -> int:
    """Allinea al fotogramma: il testo compare a fotogrammi interi, il suono deve fare uguale."""
    return round(round(ms * fps / 1000) * 1000 / fps)


def plan_sounds(
    look: dict[str, Any],
    events: list[SoundEvent],
    catalog: dict[str, list[dict[str, Any]]],
    loudness: Callable[[dict[str, Any]], float | None] = lambda s: None,
) -> list[dict[str, Any]]:
    """Sceglie i suoni per gli eventi importanti (non per ogni scritta).

    - tipo di suono dalla tabella dello stile (sound.events), varianti a rotazione;
    - picco del suono allineato al fotogramma in cui l'elemento compare;
    - eventi più vicini di sound.min_gap_ms: resta il più importante;
    - volume relativo alla voce: il suono deve stare `relative_db` sotto la voce normalizzata
      (le guide di mix per social danno effetti 12-18 dB sotto il parlato).
    """
    snd = look["sound"]
    table = snd["events"]
    gap = snd.get("min_gap_ms", 800)
    chosen: list[SoundEvent] = []
    for ev in sorted(events, key=lambda e: e.at_ms):
        if not table.get(ev.kind):
            continue
        if chosen and ev.at_ms - chosen[-1].at_ms < gap:
            if EVENT_PRIORITY.get(ev.kind, 1) > EVENT_PRIORITY.get(chosen[-1].kind, 1):
                chosen[-1] = ev
            continue
        chosen.append(ev)

    out: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for ev in chosen:
        sfx = table[ev.kind]
        variants = catalog.get(sfx, [])
        if not variants:
            continue
        n = used.get(sfx, 0)
        used[sfx] = n + 1
        s = variants[n % len(variants)]
        family = s.get("family", "textures")
        target = snd.get("voice_lufs", -14.0) + snd.get("relative_db", {}).get(family, -18.0)
        measured = loudness(s)
        # senza misura: il livello del catalogo, abbassato di 12 dB (prudente)
        gain_db = target - measured if measured is not None else float(s["level_db"]) - 12
        at = _snap(ev.at_ms)
        out.append(
            {
                "type": sfx,
                "file": s["file"],
                "kind": ev.kind,
                "reason": ev.reason,
                "event_ms": at,
                "from_ms": max(0, at - int(s.get("peak_ms", 0))),
                "gain_db": round(gain_db, 1),
                "volume": round(min(1.0, 10 ** (gain_db / 20)), 4),
            }
        )
    return out


BLOCK_GAP_MS = 1500  # un taglio che toglie almeno 1,5 s separa due idee: è una vera transizione
FRAME = 1000 / FPS


def sound_events(
    look: dict[str, Any],
    hook: dict[str, Any] | None,
    captions: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    pieces: list[Piece],
) -> list[SoundEvent]:
    """I momenti che meritano un suono, all'istante in cui l'elemento si vede davvero
    (stessi tempi delle animazioni di motion/src/StyledReel.tsx).

    Solo dove serve, come nei reference: l'hook, un elemento che compare (pop-up/card),
    una vera transizione tra blocchi, la parola chiave di un concetto. Mai su ogni scritta
    e mai sui semplici jump cut che tolgono le pause.
    """
    events: list[SoundEvent] = []
    if hook:
        if look["hook"]["animation"] == "reveal":
            # la riga grande parte dopo 7 fotogrammi e le prime lettere si vedono dopo ~3
            events.append(SoundEvent(round(10 * FRAME), "hook", "hook: entra la riga grande"))
        else:
            events.append(SoundEvent(0, "hook", "hook: la copertina salta dentro"))
    for card in cards:
        if not card.get("sound", True):
            continue
        # vetro: molla morbida, metà opacità dopo ~5 fotogrammi; sticker: pop quasi subito
        delay = 2 * FRAME if look["cards"]["kind"] == "sticker" else 5 * FRAME
        title = f" «{card['title']}»" if card.get("title") else ""
        events.append(
            SoundEvent(round(card["from_ms"] + delay), "card_in", f"compare il pop-up{title}")
        )
    for prev, cur in zip(pieces, pieces[1:], strict=False):
        removed = cur.src_start - prev.src_end
        if removed >= BLOCK_GAP_MS:
            events.append(
                SoundEvent(
                    cur.out_start,
                    "cut",
                    f"cambio di blocco (tolta pausa di {removed / 1000:.1f} s)",
                )
            )
    pop_whole = look["captions"]["animation"] == "pop"
    gap = look["sound"].get("emphasis_gap_ms", 6000)
    marked = [e.at_ms for e in events if e.kind in ("hook", "card_in")]
    last = -10**9
    for c in captions:
        i = c["emphasis"]
        if i < 0:
            continue
        word = c["words"][i]["text"].strip(".,!?;:")
        if pop_whole:  # la frase salta dentro intera: la parola chiave si vede subito
            at = c["from_ms"]
        else:  # entrata sfocata parola per parola: si legge a metà dissolvenza
            at = max(c["from_ms"], c["words"][i]["from_ms"]) + round(3 * FRAME)
        # di rado: un pop-up vicino segna già il momento; e non una parola chiave dopo l'altra
        if at - last < gap or any(abs(at - m) < 2000 for m in marked):
            continue
        events.append(SoundEvent(at, "emphasis", f"parola chiave «{word}»"))
        last = at
    return events


def hook_lines(text: str) -> list[dict[str, str]]:
    """Righe dell'hook con il loro ruolo nella gerarchia: kicker (aggancio piccolo),
    big (la riga che si legge in un secondo), sub (sottotitolo piccolo).
    `*riga*` indica la grande; altrimenti è la seconda (o l'unica)."""
    raw = [x.strip() for x in re.split(r"\||\n", text) if x.strip()]
    marked = [i for i, x in enumerate(raw) if x.startswith("*") and x.endswith("*") and len(x) > 2]
    big = marked[0] if marked else (0 if len(raw) == 1 else 1)
    out = []
    for i, line in enumerate(raw):
        role = "big" if i == big else ("kicker" if i < big else "sub")
        out.append({"text": line.strip("*").strip() if i == big else line, "role": role})
    return out


def _cards(project_dir: Path, pieces: list[Piece], chunks, look) -> list[dict[str, Any]]:
    """Pop-up del progetto (popups.json; la prima volta: le immagini AI già generate).
    Compaiono quando viene detta la parola a cui sono ancorati; i rifiutati no."""
    if look["cards"]["kind"] == "none":
        return []
    data = pops.seed_from_ai_requests(pops.load(project_dir), project_dir, look.get("style"))
    out = []
    for item in pops.sorted_items(data):
        if item.status == "rejected" or not item.visible_for(look.get("style")):
            continue
        if item.kind == "image" and not item.image:
            continue  # immagine non ancora generata
        at = to_out(pieces, item.at_ms)
        if at is None:
            continue  # il punto è in una parte tagliata
        title = item.title
        if not title and item.kind == "image":
            for c in chunks:
                if c.start_ms - 200 <= at <= c.end_ms + 600 and not c.event:
                    idx = emphasis_index([w.text for w in c.words])
                    if idx >= 0:
                        title = re.sub(r"[^\w' ]", "", c.words[idx].text)
        out.append(
            {
                "id": item.id,
                "src": item.image if item.kind == "image" else None,
                "emoji": item.emoji if item.kind == "emoji" else None,
                "from_ms": at,
                "to_ms": at + item.duration_ms,
                "title": title,
                "sound": item.sound,
                "kind": item.kind,
                "placement": item.placement,
                "size": item.size,
                "side": item.side,
            }
        )
    # uno alla volta: stanno nello stesso punto dello schermo, il nuovo sostituisce il vecchio
    out.sort(key=lambda c: c["from_ms"])
    for prev, nxt in zip(out, out[1:], strict=False):
        prev["to_ms"] = min(prev["to_ms"], nxt["from_ms"])
    return [c for c in out if c["to_ms"] - c["from_ms"] >= 300]


def build_props(
    *,
    project_dir: Path,
    tl: Timeline,
    eff: list[EffectiveRange],
    look: dict[str, Any],
    window: tuple[int, int],
    source_rel: str,
    hook_text: str | None,
    catalog: dict[str, list[dict[str, Any]]] | None = None,
    loudness: Callable[[dict[str, Any]], float | None] = lambda s: None,
) -> tuple[dict[str, Any], list[Piece]]:
    start, end = window
    pieces = pieces_in_window(eff, start, end)
    if not pieces:
        raise RenderError("nella finestra scelta è tutto tagliato: scegli un altro istante")
    duration = pieces[-1].out_end
    words = _timed_words(tl, pieces)
    cap = look["captions"]
    chunks = build_chunks(words, cap["max_words"], cap["max_chars"])
    use_emph = cap["emphasis"] is not None
    captions = []
    for i, c in enumerate(chunks):
        texts = [w.text for w in c.words]
        captions.append(
            {
                "from_ms": c.start_ms,
                "to_ms": c.end_ms + 250,
                "words": [{"text": w.text, "from_ms": w.start_ms} for w in c.words],
                "emphasis": emphasis_index(texts) if use_emph else -1,
                "color": cap["colors"][i % len(cap["colors"])],
            }
        )
    hook = None
    hook_end = 0
    if hook_text and look["hook"]:
        hook_end = look["hook"]["duration_ms"]
        hook = {"lines": hook_lines(hook_text), "to_ms": hook_end}
        # l'hook è la copertina: niente sottotitoli sotto. Le frasi a cavallo partono dopo.
        captions = [
            {**c, "from_ms": max(c["from_ms"], hook_end)} for c in captions if c["to_ms"] > hook_end
        ]
    cards = _cards(project_dir, pieces, chunks, look)
    for card in cards:  # le card non coprono l'hook: entrano subito dopo
        if card["from_ms"] < hook_end:
            card["to_ms"] += hook_end + 150 - card["from_ms"]
            card["from_ms"] = hook_end + 150
    lt = look["lower_third"]
    lower_third = None
    if lt:
        # il lower third è legato all'inizio del video: compare solo se la finestra lo contiene
        a, b = lt["show_ms"]
        if start == 0:
            shift = max(0, hook_end + 200 - a)
            lower_third = {**lt, "from_ms": a + shift, "to_ms": b + shift}
    sounds = plan_sounds(
        look,
        sound_events(look, hook, captions, cards, pieces),
        catalog if catalog is not None else _catalog(),
        loudness=loudness,
    )
    v = tl.sources.camera.video
    portrait = v.display_height >= v.display_width
    props = {
        "fps": FPS,
        "width": 1080 if portrait else 1920,
        "height": 1920 if portrait else 1080,
        "durationInFrames": max(1, round(duration / 1000 * FPS)),
        "look": look,
        "video": {
            "src": source_rel,
            "pieces": [
                {"from_ms": p.out_start, "to_ms": p.out_end, "src_ms": p.src_start - start}
                for p in pieces
            ],
        },
        "phrases": _phrase_starts(words),
        "captions": captions,
        "hook": hook,
        "cards": cards,
        "lowerThird": lower_third,
        "sounds": sounds,
    }
    return props, pieces


def _npx() -> str:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if exe is None:
        raise RenderError("npx non trovato: installa Node.js")
    return exe


def run_remotion(
    props: dict[str, Any], props_path: Path, out: Path, public_dir: Path, *, frame: int | None
) -> Path:
    if not (MOTION_DIR / "node_modules").is_dir():
        raise RenderError("Remotion non installato: cd motion && npm install")
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_npx(), "remotion"]
    cmd += (
        ["still", "src/index.ts", COMPOSITION, str(out), f"--frame={frame}"]
        if frame is not None
        # poca concorrenza: con troppi worker l'estrazione dei fotogrammi va in timeout
        else [
            "render",
            "src/index.ts",
            COMPOSITION,
            str(out),
            "--codec=h264",
            "--crf=18",
            "--concurrency=2",
        ]
    )
    cmd += [
        f"--props={props_path}",
        f"--public-dir={public_dir}",
        "--log=error",
        "--timeout=120000",
    ]
    env = dict(os.environ)
    opts = env.get("NODE_OPTIONS", "")
    if "--use-system-ca" not in opts:
        env["NODE_OPTIONS"] = (opts + " --use-system-ca").strip()
    proc = subprocess.run(
        cmd, cwd=MOTION_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, check=False,
    )  # fmt: skip
    if proc.returncode != 0 or not out.exists():
        raise RenderError(f"Remotion: {(proc.stderr or proc.stdout).strip()[-800:]}")
    return out


def stage_sounds(sounds: list[dict[str, Any]], work: Path) -> None:
    """Copia i suoni usati nella cartella pubblica del render (Remotion li legge da lì)."""
    for s in sounds:
        dest = work / "render" / "sfx" / s["file"]
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LIBRARY_DIR / s["file"], dest)
        s["src"] = "render/sfx/" + s["file"]


__all__ = [
    "Piece",
    "RenderError",
    "build_props",
    "ensure_source",
    "pieces_in_window",
    "plan_sounds",
    "run_remotion",
    "stage_sounds",
    "to_out",
]
