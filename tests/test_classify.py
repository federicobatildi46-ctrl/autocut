import pytest

from autocut.ingest.classify import AmbiguousClassification, assess, classify
from tests.fakes import info, iphone_ffprobe, obs_ffprobe

IPHONE = "IMG_4821.MOV"
OBS = "2026-11-04 15-22-10.mkv"


def test_iphone_is_camera():
    a = assess(info(IPHONE, iphone_ffprobe()))
    assert a.label == "camera"
    assert "apple.quicktime.make=Apple" in a.signal_names("camera")
    assert "model=iPhone 18 Pro" in a.signal_names("camera")
    assert a.screen_score == 0


def test_obs_mkv_is_screen():
    a = assess(info(OBS, obs_ffprobe()))
    assert a.label == "screen"
    assert set(a.signal_names("screen")) >= {
        "name~YYYY-MM-DD HH-MM-SS",
        "container=mkv",
        "no_mobile_metadata",
        "1920x1080",
    }


def test_obs_mp4_is_screen():
    a = assess(info("2026-11-04 15-22-10.mp4", obs_ffprobe(matroska=False)))
    assert a.label == "screen"


def test_iphone_without_tags_still_camera_by_name_container_and_4k():
    a = assess(info(IPHONE, iphone_ffprobe(apple_tags=False)))
    assert a.camera_score == 3 and a.screen_score == 1
    assert a.label == "camera"


def test_iphone_portrait_is_camera():
    a = assess(info(IPHONE, iphone_ffprobe(rotation=-90)))
    assert a.label == "camera"


def test_camera_plus_screen():
    c = classify([assess(info(OBS, obs_ffprobe())), assess(info(IPHONE, iphone_ffprobe()))])
    assert c.camera.info.file_name == IPHONE
    assert c.screen is not None and c.screen.info.file_name == OBS
    assert c.warnings == ()


def test_single_video_is_always_camera():
    c = classify([assess(info(IPHONE, iphone_ffprobe()))])
    assert c.screen is None and c.warnings == ()


def test_single_video_that_looks_like_screen_warns():
    c = classify([assess(info(OBS, obs_ffprobe()))])
    assert c.camera.info.file_name == OBS
    assert c.warnings[0][0] == "single_video_not_camera_like"


def test_two_cameras_is_ambiguous():
    with pytest.raises(AmbiguousClassification) as exc:
        classify(
            [
                assess(info("IMG_1.MOV", iphone_ffprobe())),
                assess(info("IMG_2.MOV", iphone_ffprobe())),
            ]
        )
    assert "2 camera" in str(exc.value)
    assert "--camera" in str(exc.value)


def test_unrecognized_extra_file_is_ambiguous():
    unknown = assess(info("clip.mp4", iphone_ffprobe(apple_tags=False, width=1280, height=720)))
    assert unknown.label == "unknown"
    with pytest.raises(AmbiguousClassification, match="1 non riconosciuti"):
        classify(
            [assess(info(IPHONE, iphone_ffprobe())), assess(info(OBS, obs_ffprobe())), unknown]
        )


def test_empty_folder():
    with pytest.raises(AmbiguousClassification, match="nessun video"):
        classify([])
