"""Media di anteprima per l'editor, tutti in projects/<nome>/work/ (rigenerabili).

- proxy: H.264 8 bit, lato lungo max 1280 px, GOP corto per uno scrubbing fluido. Serve
  perché i raw iPhone (HEVC 10 bit HDR) non sempre si riproducono nel browser.
- miniature per la striscia della timeline;
- forma d'onda (picchi ogni 10 ms) per la traccia audio.
Il raw è solo letto. Con --range il proxy copre solo il tratto (offset in `offset_ms`).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models.timeline import Timeline

THUMB_HEIGHT = 72
MAX_THUMBS = 300
WAVE_RATE = 8000
WAVE_BUCKET_MS = 10


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorMedia:
    proxy: Path
    offset_ms: int  # tempo camera dello 0 del proxy
    duration_ms: int
    thumbs_dir: Path
    thumb_interval_ms: int
    thumb_count: int
    waveform: Path


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MediaError("ffmpeg non trovato nel PATH")
    return exe


def _run(cmd: list[str], what: str) -> bytes:
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[-500:]
        raise MediaError(f"{what}: {msg}")
    return proc.stdout


def _key(tl: Timeline) -> str:
    fp = tl.sources.camera.fingerprint.split(":", 1)[-1][:12]
    rng = tl.run.range
    return fp + (f"-{rng.start_ms}-{rng.end_ms}" if rng else "")


def _span(tl: Timeline) -> tuple[int, int]:
    rng = tl.run.range
    return (rng.start_ms, rng.end_ms) if rng else (0, tl.sources.camera.duration_ms)


def ensure_proxy(work: Path, tl: Timeline, src: Path) -> Path:
    dest = work / f"proxy-{_key(tl)}.mp4"
    if dest.exists():
        return dest
    work.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".partial.mp4")
    start, end = _span(tl)
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if tl.run.range:
        cmd += ["-ss", f"{start / 1000:.3f}", "-to", f"{end / 1000:.3f}"]
    scale = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
    cmd += [
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"{scale},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", "15",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        str(tmp),
    ]  # fmt: skip
    try:
        _run(cmd, "proxy")
    except MediaError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return dest


def thumb_interval_ms(duration_ms: int) -> int:
    step = max(1000, duration_ms / MAX_THUMBS)
    return int(math.ceil(step / 500) * 500)


def ensure_thumbs(work: Path, tl: Timeline, proxy: Path) -> tuple[Path, int, int]:
    start, end = _span(tl)
    interval = thumb_interval_ms(end - start)
    folder = work / f"thumbs-{_key(tl)}-{interval}"
    done = folder / "done.json"
    if done.exists():
        return folder, interval, json.loads(done.read_text())["count"]
    folder.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(proxy),
            "-vf",
            f"fps=1000/{interval},scale=-2:{THUMB_HEIGHT}",
            "-q:v",
            "6",
            str(folder / "%05d.jpg"),
        ],  # fmt: skip
        "miniature",
    )
    count = len(list(folder.glob("*.jpg")))
    done.write_text(json.dumps({"count": count, "interval_ms": interval}))
    return folder, interval, count


def ensure_waveform(work: Path, tl: Timeline, proxy: Path) -> Path:
    dest = work / f"waveform-{_key(tl)}.json"
    if dest.exists():
        return dest
    raw = _run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(proxy),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(WAVE_RATE),
            "-f",
            "s16le",
            "-",
        ],  # fmt: skip
        "forma d'onda",
    )
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    step = WAVE_RATE * WAVE_BUCKET_MS // 1000
    peaks = []
    for i in range(0, len(samples), step):
        chunk = samples[i : i + step]
        peaks.append(max(max(chunk), -min(chunk)) if chunk else 0)
    top = max(peaks) if peaks and max(peaks) > 0 else 1
    norm = [round(100 * p / top) for p in peaks]
    dest.write_text(json.dumps({"bucket_ms": WAVE_BUCKET_MS, "peaks": norm}))
    return dest


def grab_frame(proxy: Path, seconds: float, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{max(0.0, seconds):.3f}",
            "-i",
            str(proxy),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(dest),
        ],  # fmt: skip
        "frame",
    )
    return dest


def prepare(
    project_dir: Path, tl: Timeline, src: Path, log: Callable[[str], None] = lambda s: None
) -> EditorMedia:
    work = project_dir / "work"
    log("proxy video di anteprima...")
    proxy = ensure_proxy(work, tl, src)
    log("miniature della timeline...")
    thumbs, interval, count = ensure_thumbs(work, tl, proxy)
    log("forma d'onda...")
    wave = ensure_waveform(work, tl, proxy)
    start, end = _span(tl)
    return EditorMedia(
        proxy=proxy,
        offset_ms=start,
        duration_ms=end - start,
        thumbs_dir=thumbs,
        thumb_interval_ms=interval,
        thumb_count=count,
        waveform=wave,
    )
