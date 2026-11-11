"""B-roll e voice-over: clip e immagini di supporto sopra il parlato, e una voce fuori campo.

Vivono in projects/<nome>/broll.json (i file caricati in work/broll/ e work/voiceover/):
- B-roll: una foto o un video a tutto schermo SOPRA la ripresa per un tratto; la voce di chi
  parla continua (il B-roll è muto). Nell'export si cuce dentro l'estratto della camera, come
  le clip di «Genera con Higgsfield».
- Voice-over: una traccia audio caricata (registrata col telefono) che parte in un punto e
  suona sopra il video; può zittire la voce della ripresa mentre parla.

I tempi sono ms sull'asse della camera (come timeline.json): restano validi se cambiano i tagli.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .vfx import FPS, _ffmpeg, _run, _setparams, color_tags

BROLL_FILE = "broll.json"
BROLL_DIR = Path("work") / "broll"
VOICE_DIR = Path("work") / "voiceover"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".aif", ".aiff", ".caf")
MAX_VIDEO_BYTES = 1_500_000_000
MAX_IMAGE_BYTES = 40_000_000
MAX_AUDIO_BYTES = 400_000_000
MIN_MS, MAX_BROLL_MS = 500, 120_000
IMAGE_DEFAULT_MS = 3000
VIDEO_DEFAULT_MS = 4000


class BrollError(ValueError):
    pass


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^br_\d{4,}$")
    kind: Literal["image", "video"]
    file: str  # nome in work/broll/
    name: str = Field(default="", max_length=80)
    at_ms: int = Field(ge=0)
    duration_ms: int = Field(default=VIDEO_DEFAULT_MS, ge=MIN_MS, le=MAX_BROLL_MS)
    src_ms: int = Field(default=0, ge=0)  # da dove parte dentro il video caricato
    media_ms: int = Field(default=0, ge=0)  # durata del file (0 per le foto)
    enabled: bool = True
    updated_at: str = ""


class Voice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^vo_\d{4,}$")
    file: str  # nome in work/voiceover/
    name: str = Field(default="", max_length=80)
    at_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=MIN_MS)  # durata del file
    gain_db: float = Field(default=0.0, ge=-24, le=12)
    mute_camera: bool = True  # mentre parla, la voce della ripresa tace
    enabled: bool = True
    updated_at: str = ""


class BrollFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    clips: list[Clip] = Field(default_factory=list)
    voices: list[Voice] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def path_for(project_dir: Path) -> Path:
    return project_dir / BROLL_FILE


def load(project_dir: Path) -> BrollFile:
    p = path_for(project_dir)
    if not p.exists():
        return BrollFile()
    try:
        return BrollFile.model_validate_json(p.read_bytes())
    except ValidationError as exc:
        raise BrollError(f"{p}: {exc}") from exc


def save(project_dir: Path, data: BrollFile) -> None:
    p = path_for(project_dir)
    tmp = p.with_suffix(".partial")
    tmp.write_text(data.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _next_id(prefix: str, ids: list[str]) -> str:
    nums = [int(i.split("_")[1]) for i in ids if re.fullmatch(rf"{prefix}_\d+", i)]
    return f"{prefix}_{max(nums, default=0) + 1:04d}"


def safe_name(name: str) -> str:
    """Nome file sicuro (niente percorsi, niente caratteri strani), conserva l'estensione."""
    base = Path(str(name).replace("\\", "/")).name
    stem = re.sub(r"[^\w.-]+", "_", Path(base).stem, flags=re.UNICODE).strip("._") or "file"
    return stem[:60] + Path(base).suffix.lower()


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    raise BrollError(
        "formato non supportato: servono video (mp4, mov, webm), foto (jpg, png, webp) "
        "o audio (m4a, mp3, wav)"
    )


def size_limit(kind: str) -> int:
    return {"video": MAX_VIDEO_BYTES, "image": MAX_IMAGE_BYTES}.get(kind, MAX_AUDIO_BYTES)


def probe(path: Path) -> dict[str, Any]:
    """Durata (ms) e misure del file, con ffprobe. Solleva BrollError se non è un media valido."""
    exe = shutil.which("ffprobe")
    if exe is None:
        raise BrollError("ffprobe non trovato nel PATH")
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(path)], capture_output=True, text=True, check=False,
    )  # fmt: skip
    try:
        info = json.loads(proc.stdout)
        streams = info.get("streams") or []
    except ValueError:
        streams = []
        info = {}
    if proc.returncode != 0 or not streams:
        raise BrollError("il file non si apre: è rovinato o non è un media valido")
    try:
        dur = round(float(info.get("format", {}).get("duration") or 0) * 1000)
    except ValueError:
        dur = 0
    return {
        "duration_ms": dur,
        "has_video": any(s.get("codec_type") == "video" for s in streams),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def _stored(project_dir: Path, folder: Path, name: str) -> Path:
    dest_dir = project_dir / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    n = 2
    while dest.exists():  # un nome uguale non ne cancella un altro
        dest = dest_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    return dest


def staging(project_dir: Path, name: str) -> Path:
    """Dove scrivere un file in arrivo (si sposta nella cartella giusta dopo il controllo)."""
    d = project_dir / "work" / "broll" / "_incoming"
    d.mkdir(parents=True, exist_ok=True)
    return d / safe_name(name)


def add_clip(project_dir: Path, incoming: Path, name: str, at_ms: int) -> Clip:
    """Mette un file caricato (video o foto) in B-roll alla posizione data."""
    kind = kind_of(name)
    if kind == "audio":
        raise BrollError("questo è un audio: caricalo come voice-over (scheda Audio)")
    info = probe(incoming)
    if not info["has_video"]:
        raise BrollError("nel file non c'è nessuna immagine")
    dest = _stored(project_dir, BROLL_DIR, safe_name(name))
    shutil.move(str(incoming), dest)
    data = load(project_dir)
    media_ms = info["duration_ms"] if kind == "video" else 0
    dur = min(VIDEO_DEFAULT_MS, media_ms) if kind == "video" and media_ms else IMAGE_DEFAULT_MS
    clip = Clip(
        id=_next_id("br", [c.id for c in data.clips]), kind=kind, file=dest.name,  # type: ignore[arg-type]  # noqa: E501
        name=Path(name).stem[:80], at_ms=max(0, at_ms), duration_ms=max(MIN_MS, dur),
        media_ms=media_ms, updated_at=_now(),
    )  # fmt: skip
    data.clips.append(clip)
    save(project_dir, data)
    return clip


def add_voice(project_dir: Path, incoming: Path, name: str, at_ms: int) -> Voice:
    if kind_of(name) == "image":
        raise BrollError("questa è una foto: mettila nel B-roll")
    info = probe(incoming)
    if not info["has_audio"]:
        raise BrollError("nel file non c'è nessun audio")
    if info["duration_ms"] < MIN_MS:
        raise BrollError("l'audio è troppo corto")
    dest = _stored(project_dir, VOICE_DIR, safe_name(name))
    shutil.move(str(incoming), dest)
    data = load(project_dir)
    voice = Voice(
        id=_next_id("vo", [v.id for v in data.voices]), file=dest.name,
        name=Path(name).stem[:80], at_ms=max(0, at_ms), duration_ms=info["duration_ms"],
        updated_at=_now(),
    )  # fmt: skip
    data.voices.append(voice)
    save(project_dir, data)
    return voice


def edit(project_dir: Path, item_id: str, fields: dict[str, Any]) -> None:
    data = load(project_dir)
    pool = data.clips if item_id.startswith("br_") else data.voices
    item = next((x for x in pool if x.id == item_id), None)
    if item is None:
        raise BrollError(f"{item_id} non esiste")
    allowed = (
        {"at_ms", "duration_ms", "src_ms", "enabled", "name"}
        if item_id.startswith("br_")
        else {"at_ms", "gain_db", "mute_camera", "enabled", "name"}
    )
    unknown = set(fields) - allowed
    if unknown:
        raise BrollError(f"campi non modificabili: {', '.join(sorted(unknown))}")
    merged = {**item.model_dump(), **fields, "updated_at": _now()}
    if item_id.startswith("br_"):
        c = Clip.model_validate(merged)
        if c.kind == "video" and c.media_ms:  # non oltre la fine del video caricato
            c = c.model_copy(update={"src_ms": min(c.src_ms, max(0, c.media_ms - MIN_MS))})
        pool[pool.index(item)] = c  # type: ignore[index]
    else:
        pool[pool.index(item)] = Voice.model_validate(merged)  # type: ignore[index]
    save(project_dir, data)


def remove(project_dir: Path, item_id: str) -> None:
    """Toglie dall'elenco. Il file resta nella cartella del progetto: così Annulla lo rimette."""
    data = load(project_dir)
    pool = data.clips if item_id.startswith("br_") else data.voices
    item = next((x for x in pool if x.id == item_id), None)
    if item is None:
        raise BrollError(f"{item_id} non esiste")
    pool.remove(item)  # type: ignore[arg-type]
    save(project_dir, data)


def media_path(project_dir: Path, folder: str, name: str) -> Path | None:
    base = (project_dir / (BROLL_DIR if folder == "broll" else VOICE_DIR)).resolve()
    p = (base / name).resolve()
    return p if p.parent == base and p.is_file() else None


# --- render ------------------------------------------------------------------------------------


def active_clips(project_dir: Path) -> list[Clip]:
    return [
        c for c in load(project_dir).clips
        if c.enabled and (project_dir / BROLL_DIR / c.file).is_file()
    ]  # fmt: skip


def active_voices(project_dir: Path) -> list[Voice]:
    return [
        v for v in load(project_dir).voices
        if v.enabled and (project_dir / VOICE_DIR / v.file).is_file()
    ]  # fmt: skip


def _dims(path: Path) -> tuple[int, int]:
    exe = shutil.which("ffprobe")
    if exe:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=False,
        ).stdout.strip().split(",")  # fmt: skip
        if len(out) == 2 and all(x.isdigit() for x in out):
            return int(out[0]), int(out[1])
    return 1080, 1920


def bake(project_dir: Path, source: Path, start_ms: int, end_ms: int) -> Path:
    """Estratto della camera con i B-roll attivi nella finestra cuciti sopra (cache per contenuto).
    L'audio resta quello della ripresa: il B-roll è muto."""
    clips = [c for c in active_clips(project_dir)
             if c.at_ms < end_ms and c.at_ms + c.duration_ms > start_ms]  # fmt: skip
    if not clips:
        return source
    key = hashlib.sha1()
    for c in clips:
        f = project_dir / BROLL_DIR / c.file
        key.update(f"{c.id}:{c.at_ms}:{c.duration_ms}:{c.src_ms}:{f.stat().st_mtime_ns}".encode())
    key.update(f"{start_ms}:{end_ms}".encode())
    dest = source.with_name(f"{source.stem}-broll-{key.hexdigest()[:10]}.mp4")
    if dest.exists():
        return dest
    w, h = _dims(source)
    tags = color_tags(source)
    inputs: list[str] = ["-i", str(source)]
    chains, last = [], "0:v"
    for i, c in enumerate(clips, start=1):
        a, b = max(c.at_ms, start_ms), min(c.at_ms + c.duration_ms, end_ms)
        dur, off = (b - a) / 1000, (a - start_ms) / 1000
        path = str(project_dir / BROLL_DIR / c.file)
        if c.kind == "image":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", path]
        else:
            skip = (c.src_ms + (a - c.at_ms)) / 1000
            inputs += ["-ss", f"{skip:.3f}", "-t", f"{dur:.3f}", "-i", path]
        fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        # un video più corto della finestra resta fermo sull'ultimo fotogramma
        hold = f",tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f}"
        chains.append(f"[{i}:v]fps={FPS},{fit}{hold},setpts=PTS-STARTPTS+{off:.3f}/TB[b{i}]")
        chains.append(f"[{last}][b{i}]overlay=eof_action=pass:repeatlast=0[v{i}]")
        last = f"v{i}"
    chains.append(f"[{last}]format=yuv420p{_setparams(tags)}[vout]")
    meta: list[str] = []
    flags = (("color_space", "-colorspace"), ("color_primaries", "-color_primaries"),
             ("color_transfer", "-color_trc"), ("color_range", "-color_range"))  # fmt: skip
    for key_, flag in flags:
        if tags.get(key_):
            meta += [flag, tags[key_]]
    tmp = dest.with_name(dest.stem + ".partial.mp4")
    _run([_ffmpeg(), "-v", "error", "-nostdin", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[vout]", "-map", "0:a?", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
          "-crf", "16", "-g", str(FPS), *meta, "-c:a", "copy", str(tmp)],
         "B-roll nel video")  # fmt: skip
    tmp.replace(dest)
    return dest


def render_voices(
    project_dir: Path, work: Path, to_out: Any, pieces: list[Any]
) -> list[dict[str, Any]]:
    """Voice-over per Remotion: partenza sul montato (dopo i tagli) e file nella cartella pubblica.
    Se il punto cade in una parte tolta parte dal primo tratto dopo."""
    out = []
    for v in active_voices(project_dir):
        at = to_out(pieces, v.at_ms)
        if at is None:
            at = next((p.out_start for p in pieces if p.src_start >= v.at_ms), None)
        if at is None:
            continue
        src = project_dir / VOICE_DIR / v.file
        boost = v.gain_db > 0  # Remotion non alza oltre 1: l'aumento lo fa ffmpeg (con limitatore)
        name = f"{Path(v.file).stem}-{v.gain_db:+.1f}dB.wav" if boost else v.file
        dest = work / "render" / "voiceover" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        stamp = f"{src.stat().st_mtime_ns}"
        marker = dest.with_name(dest.name + ".src")
        if not dest.exists() or not marker.exists() or marker.read_text() != stamp:
            if boost:
                _run([_ffmpeg(), "-v", "error", "-nostdin", "-y", "-i", str(src), "-af",
                      f"volume={v.gain_db}dB,alimiter=limit=0.97", "-c:a", "pcm_s16le", str(dest)],
                     "voice-over")  # fmt: skip
            else:
                shutil.copy2(src, dest)
            marker.write_text(stamp)
        out.append({
            "id": v.id, "src": f"render/voiceover/{name}", "from_ms": int(at),
            "dur_ms": v.duration_ms,
            "volume": 1.0 if boost else round(10 ** (v.gain_db / 20), 4),
            "mute_camera": v.mute_camera,
        })  # fmt: skip
    return out
