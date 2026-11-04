"""Output ffprobe finti, modellati su iPhone e OBS reali (solo i campi che leggiamo)."""

from __future__ import annotations

from pathlib import Path

from autocut.ingest.probe import ProbeInfo, parse_probe


def iphone_ffprobe(
    *,
    width: int = 3840,
    height: int = 2160,
    rotation: int | None = None,
    duration: str = "182.340000",
    avg_rate: str = "60/1",
    real_rate: str = "60/1",
    apple_tags: bool = True,
    audio: bool = True,
) -> dict:
    video = {
        "index": 0,
        "codec_name": "hevc",
        "codec_type": "video",
        "width": width,
        "height": height,
        "r_frame_rate": real_rate,
        "avg_frame_rate": avg_rate,
        "start_time": "0.000000",
        "duration": duration,
    }
    if rotation is not None:
        video["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": rotation}]
    streams = [video]
    if audio:
        streams.append(
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "start_time": "0.000000",
            }
        )
    tags = {"creation_time": "2026-11-04T14:00:00.000000Z"}
    if apple_tags:
        tags |= {
            "com.apple.quicktime.make": "Apple",
            "com.apple.quicktime.model": "iPhone 18 Pro",
            "com.apple.quicktime.software": "26.1",
        }
    return {
        "streams": streams,
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": duration,
            "tags": tags,
        },
    }


def obs_ffprobe(
    *,
    width: int = 1920,
    height: int = 1080,
    duration: str = "200.000000",
    matroska: bool = True,
    audio: bool = True,
) -> dict:
    streams = [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_type": "video",
            "width": width,
            "height": height,
            "r_frame_rate": "60/1",
            "avg_frame_rate": "60/1",
            "start_time": "0.000000",
        }
    ]
    if audio:
        streams.append(
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "start_time": "0.000000",
            }
        )
    return {
        "streams": streams,
        "format": {
            "format_name": "matroska,webm" if matroska else "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": duration,
            "tags": {"ENCODER": "Lavf61.7.100"},
        },
    }


def info(name: str, data: dict, folder: Path | None = None) -> ProbeInfo:
    return parse_probe((folder or Path("raw")) / name, data)
