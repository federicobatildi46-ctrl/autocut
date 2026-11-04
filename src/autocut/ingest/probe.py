"""Lettura dei metadati con ffprobe (sola lettura: il file non viene mai toccato)."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..models.timeline import AudioStream, VideoStream

FFPROBE_ARGS = ("-v", "error", "-print_format", "json", "-show_format", "-show_streams")

# Differenza relativa oltre la quale r_frame_rate e avg_frame_rate indicano un VFR.
VFR_TOLERANCE = 0.01


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProbeInfo:
    path: Path
    file_name: str
    container: str  # dall'estensione: mov, mp4, mkv, ...
    format_name: str  # da ffprobe, es. "mov,mp4,m4a,3gp,3g2,mj2" o "matroska,webm"
    duration_ms: int
    video: VideoStream
    audio: AudioStream | None
    tags: Mapping[str, str] = field(default_factory=dict)  # tag di formato, chiavi minuscole


def run_ffprobe(path: Path) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise ProbeError("ffprobe non trovato nel PATH")
    proc = subprocess.run([exe, *FFPROBE_ARGS, str(path)], capture_output=True, check=False)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise ProbeError(f"ffprobe su {path.name}: {msg}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ProbeError(f"ffprobe su {path.name}: output non JSON") from exc


def probe(path: Path) -> ProbeInfo:
    return parse_probe(path, run_ffprobe(path))


# --- parsing (puro, testabile con JSON finti) --------------------------------------------


def _rate(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        r = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(r) if r > 0 else 0.0


def _ms(seconds: Any) -> int | None:
    try:
        return round(float(seconds) * 1000)
    except (TypeError, ValueError):
        return None


def _rotation(stream: Mapping[str, Any]) -> int:
    """Rotazione normalizzata a 0/90/180/270 (display matrix, o il vecchio tag `rotate`)."""
    raw: Any = None
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            raw = side["rotation"]
            break
    if raw is None:
        raw = (stream.get("tags") or {}).get("rotate")
    try:
        deg = round(float(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        deg = 0
    return (round(deg / 90) * 90) % 360


def _orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _video(stream: Mapping[str, Any]) -> VideoStream:
    w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if not w or not h:
        raise ProbeError("traccia video senza dimensioni")
    rot = _rotation(stream)
    dw, dh = (h, w) if rot in (90, 270) else (w, h)
    avg, real = _rate(stream.get("avg_frame_rate")), _rate(stream.get("r_frame_rate"))
    fps = avg or real
    vfr = bool(avg and real) and abs(real - avg) / real > VFR_TOLERANCE
    return VideoStream(
        codec=str(stream.get("codec_name") or "unknown"),
        coded_width=w,
        coded_height=h,
        rotation=rot,
        display_width=dw,
        display_height=dh,
        orientation=_orientation(dw, dh),
        fps=round(fps, 3),
        fps_mode="vfr" if vfr else "cfr",
        start_ms=_ms(stream.get("start_time")) or 0,
    )


def _audio(stream: Mapping[str, Any]) -> AudioStream:
    return AudioStream(
        codec=str(stream.get("codec_name") or "unknown"),
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
        start_ms=_ms(stream.get("start_time")) or 0,
    )


def parse_probe(path: Path, data: Mapping[str, Any]) -> ProbeInfo:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video_streams = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
    ]
    if not video_streams:
        raise ProbeError(f"{path.name}: nessuna traccia video")
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    video = _video(video_streams[0])
    duration = _ms(fmt.get("duration")) or _ms(video_streams[0].get("duration"))
    if not duration:
        raise ProbeError(f"{path.name}: durata sconosciuta")

    tags = {str(k).lower(): str(v) for k, v in (fmt.get("tags") or {}).items()}
    return ProbeInfo(
        path=path,
        file_name=path.name,
        container=path.suffix.lower().lstrip(".") or "unknown",
        format_name=str(fmt.get("format_name") or ""),
        duration_ms=duration,
        video=video,
        audio=_audio(audio_streams[0]) if audio_streams else None,
        tags=tags,
    )
