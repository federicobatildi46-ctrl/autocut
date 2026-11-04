"""Passo ingest con ffprobe finto: niente file video veri, solo file segnaposto."""

import json
from pathlib import Path

import pytest

from autocut.ingest.classify import AmbiguousClassification
from autocut.ingest.probe import ProbeError, parse_probe
from autocut.ingest.step import IngestError, list_inputs, run_ingest
from autocut.models import Timeline
from autocut.models.io import read_model
from tests.fakes import iphone_ffprobe, obs_ffprobe

IPHONE = "IMG_4821.MOV"
OBS = "2026-11-04 15-22-10.mkv"


def fake_probe(table: dict[str, dict]):
    def _probe(path: Path):
        if path.name not in table:
            raise ProbeError(f"{path.name}: sconosciuto")
        return parse_probe(path, table[path.name])

    return _probe


@pytest.fixture
def raw(tmp_path) -> Path:
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / IPHONE).write_bytes(b"camera" * 1000)
    (folder / OBS).write_bytes(b"screen" * 1000)
    (folder / "._IMG_4821.MOV").write_bytes(b"x")
    (folder / "note.txt").write_text("appunti")
    return folder


@pytest.fixture
def probe_both():
    return fake_probe({IPHONE: iphone_ffprobe(), OBS: obs_ffprobe()})


def test_list_inputs(raw):
    videos, ignored = list_inputs(raw)
    assert [p.name for p in videos] == [OBS, IPHONE]
    assert ignored == ["._IMG_4821.MOV: file di metadati macOS", "note.txt: non è un video"]


def test_auto_ingest_writes_timeline(raw, tmp_path, probe_both):
    res = run_ingest("ep12", raw, projects_root=tmp_path / "projects", probe_fn=probe_both)
    assert res.timeline_path == tmp_path / "projects" / "ep12" / "timeline.json"
    tl = read_model(res.timeline_path, Timeline)
    assert tl.detection.mode == "auto"
    assert tl.detection.camera.file_name == IPHONE
    assert tl.detection.screen is not None and tl.detection.screen.file_name == OBS
    assert "apple.quicktime.make=Apple" in tl.detection.camera.signals
    assert tl.sources.camera.audio_policy == "reference"
    assert tl.sources.screen is not None and tl.sources.screen.audio_policy == "sync_only_mute"
    assert tl.sync.status == "pending"
    assert (tl.settings.profile, tl.settings.profile_source) == ("long", "auto")
    assert tl.run.steps["ingest"].input_hash.startswith("sha256:")
    assert tl.words == [] and tl.segments == []


def test_raw_files_are_untouched(raw, tmp_path, probe_both):
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in raw.iterdir()}
    run_ingest("ep12", raw, projects_root=tmp_path / "projects", probe_fn=probe_both)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in raw.iterdir()}
    assert after == before


def test_ingest_is_deterministic(raw, tmp_path, probe_both):
    root = tmp_path / "projects"
    first = run_ingest("ep12", raw, projects_root=root, probe_fn=probe_both)
    a = first.timeline_path.read_bytes()
    run_ingest("ep12", raw, projects_root=root, probe_fn=probe_both)
    assert first.timeline_path.read_bytes() == a


def test_portrait_camera_defaults_to_short(tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / IPHONE).write_bytes(b"x")
    probe = fake_probe({IPHONE: iphone_ffprobe(rotation=-90)})
    tl = run_ingest("reel", folder, projects_root=tmp_path / "p", probe_fn=probe).timeline
    assert tl.sources.screen is None
    assert tl.sync.status == "not_applicable"
    assert (tl.settings.profile, tl.settings.pauses.threshold_ms) == ("short", 800)


def test_cli_profile_and_set_are_recorded(raw, tmp_path, probe_both):
    tl = run_ingest(
        "ep12",
        raw,
        profile="short",
        sets=["pauses.margin_ms=120"],
        projects_root=tmp_path / "p",
        probe_fn=probe_both,
    ).timeline
    assert (tl.settings.profile, tl.settings.profile_source) == ("short", "cli")
    assert tl.settings.pauses.margin_ms == 120


def test_project_settings_file_is_applied(raw, tmp_path, probe_both):
    pdir = tmp_path / "p" / "ep12"
    pdir.mkdir(parents=True)
    (pdir / "settings.json").write_text(json.dumps({"pauses": {"threshold_ms": 1200}}))
    tl = run_ingest("ep12", raw, projects_root=tmp_path / "p", probe_fn=probe_both).timeline
    assert tl.settings.pauses.threshold_ms == 1200


def test_ambiguous_folder_stops_without_writing(raw, tmp_path):
    (raw / "IMG_4822.MOV").write_bytes(b"y")
    probe = fake_probe(
        {IPHONE: iphone_ffprobe(), "IMG_4822.MOV": iphone_ffprobe(), OBS: obs_ffprobe()}
    )
    root = tmp_path / "p"
    with pytest.raises(AmbiguousClassification):
        run_ingest("ep12", raw, projects_root=root, probe_fn=probe)
    assert not (root / "ep12" / "timeline.json").exists()


def test_manual_selection(raw, tmp_path, probe_both):
    (raw / "IMG_4822.MOV").write_bytes(b"y")
    probe = fake_probe(
        {IPHONE: iphone_ffprobe(), "IMG_4822.MOV": iphone_ffprobe(), OBS: obs_ffprobe()}
    )
    tl = run_ingest(
        "ep12", raw, camera=IPHONE, screen=OBS, projects_root=tmp_path / "p", probe_fn=probe
    ).timeline
    assert tl.detection.mode == "manual"
    assert tl.detection.camera.signals[0] == "--camera"
    assert tl.detection.screen is not None and tl.detection.screen.signals[0] == "--screen"
    assert tl.detection.ignored == []  # con la scelta manuale la cartella non si scansiona


def test_single_file_instead_of_folder(raw, tmp_path, probe_both):
    tl = run_ingest(
        "ep12", raw / IPHONE, projects_root=tmp_path / "p", probe_fn=probe_both
    ).timeline
    assert tl.detection.mode == "auto"
    assert tl.detection.camera.file_name == IPHONE
    assert tl.sources.screen is None and tl.detection.ignored == []


def test_single_file_rejects_flags_and_non_videos(raw, tmp_path, probe_both):
    root = tmp_path / "p"
    with pytest.raises(IngestError, match="indica una cartella"):
        run_ingest("ep12", raw / IPHONE, camera=IPHONE, projects_root=root, probe_fn=probe_both)
    with pytest.raises(IngestError, match="non è un video"):
        run_ingest("ep12", raw / "note.txt", projects_root=root, probe_fn=probe_both)


def test_manual_camera_only_means_no_screen(raw, tmp_path, probe_both):
    tl = run_ingest(
        "ep12", raw, camera=IPHONE, projects_root=tmp_path / "p", probe_fn=probe_both
    ).timeline
    assert tl.sources.screen is None and tl.sync.status == "not_applicable"


def test_screen_flag_requires_camera_flag(raw, tmp_path, probe_both):
    with pytest.raises(IngestError, match="richiede anche --camera"):
        run_ingest("ep12", raw, screen=OBS, projects_root=tmp_path / "p", probe_fn=probe_both)


def test_camera_without_audio_is_an_error(raw, tmp_path):
    probe = fake_probe({IPHONE: iphone_ffprobe(audio=False), OBS: obs_ffprobe()})
    with pytest.raises(IngestError, match="traccia audio"):
        run_ingest("ep12", raw, projects_root=tmp_path / "p", probe_fn=probe)


def test_screen_without_audio_warns(raw, tmp_path):
    probe = fake_probe({IPHONE: iphone_ffprobe(), OBS: obs_ffprobe(audio=False)})
    tl = run_ingest("ep12", raw, projects_root=tmp_path / "p", probe_fn=probe).timeline
    assert [w.type for w in tl.warnings] == ["screen_no_audio"]


def test_range_goes_to_separate_folder_and_is_recorded(raw, tmp_path, probe_both):
    res = run_ingest(
        "ep12", raw, range_text="60-120", projects_root=tmp_path / "p", probe_fn=probe_both
    )
    assert res.project_dir.name == "ep12__range_60-120"
    assert res.timeline.run.range is not None
    assert (res.timeline.run.range.start_ms, res.timeline.run.range.end_ms) == (60000, 120000)


def test_range_beyond_camera_duration(raw, tmp_path, probe_both):
    with pytest.raises(IngestError, match="oltre la durata"):
        run_ingest(
            "ep12", raw, range_text="0-500", projects_root=tmp_path / "p", probe_fn=probe_both
        )


def test_unreadable_video_is_ignored_with_reason(raw, tmp_path):
    (raw / "rotto.mp4").write_bytes(b"z")
    probe = fake_probe({IPHONE: iphone_ffprobe(), OBS: obs_ffprobe()})
    tl = run_ingest("ep12", raw, projects_root=tmp_path / "p", probe_fn=probe).timeline
    assert any(i.startswith("rotto.mp4: illeggibile") for i in tl.detection.ignored)
