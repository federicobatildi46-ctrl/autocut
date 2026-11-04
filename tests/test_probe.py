from pathlib import Path

import pytest

from autocut.ingest.fingerprint import fingerprint
from autocut.ingest.probe import ProbeError, parse_probe
from tests.fakes import info, iphone_ffprobe, obs_ffprobe


def test_iphone_landscape():
    i = info("IMG_4821.MOV", iphone_ffprobe())
    assert i.container == "mov"
    assert i.duration_ms == 182340
    assert (i.video.display_width, i.video.display_height) == (3840, 2160)
    assert i.video.orientation == "landscape"
    assert (i.video.fps, i.video.fps_mode) == (60.0, "cfr")
    assert i.audio is not None and i.audio.sample_rate == 48000
    assert i.tags["com.apple.quicktime.make"] == "Apple"


@pytest.mark.parametrize("rotation", [-90, 90, 270])
def test_iphone_portrait_is_detected_from_display_matrix(rotation):
    i = info("IMG_4822.MOV", iphone_ffprobe(rotation=rotation))
    assert (i.video.coded_width, i.video.coded_height) == (3840, 2160)
    assert (i.video.display_width, i.video.display_height) == (2160, 3840)
    assert i.video.orientation == "portrait"
    assert i.video.rotation in (90, 270)


def test_legacy_rotate_tag():
    data = iphone_ffprobe()
    data["streams"][0]["tags"] = {"rotate": "90"}
    assert info("IMG_1.MOV", data).video.orientation == "portrait"


def test_fractional_and_variable_frame_rate():
    i = info("IMG_1.MOV", iphone_ffprobe(avg_rate="60000/1001", real_rate="60000/1001"))
    assert (i.video.fps, i.video.fps_mode) == (59.94, "cfr")
    i = info("IMG_1.MOV", iphone_ffprobe(avg_rate="5483/100", real_rate="60/1"))
    assert i.video.fps_mode == "vfr"


def test_obs_mkv_tags_are_lowercased():
    i = info("2026-11-04 15-22-10.mkv", obs_ffprobe())
    assert i.container == "mkv"
    assert i.tags["encoder"].startswith("Lavf")


def test_no_video_stream_is_an_error():
    data = iphone_ffprobe()
    data["streams"] = [s for s in data["streams"] if s["codec_type"] != "video"]
    with pytest.raises(ProbeError, match="nessuna traccia video"):
        parse_probe(Path("IMG_1.MOV"), data)


def test_cover_art_is_not_a_video_stream():
    data = iphone_ffprobe()
    data["streams"][0]["disposition"] = {"attached_pic": 1}
    with pytest.raises(ProbeError):
        parse_probe(Path("IMG_1.MOV"), data)


def test_missing_audio():
    assert info("IMG_1.MOV", iphone_ffprobe(audio=False)).audio is None


def test_fingerprint_is_stable_and_content_sensitive(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(bytes(range(256)) * 20000)  # ~5 MiB
    small = tmp_path / "small.bin"
    small.write_bytes(b"ciao")
    assert fingerprint(big) == fingerprint(big)
    assert fingerprint(small).startswith("fp1:")

    before = fingerprint(big)
    data = bytearray(big.read_bytes())
    data[-1] ^= 0xFF  # cambia l'ultimo byte
    big.write_bytes(bytes(data))
    assert fingerprint(big) != before
