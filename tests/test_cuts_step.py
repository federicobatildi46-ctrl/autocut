import pytest

from autocut.cuts.step import CutsError, run_cuts
from autocut.ingest.step import run_ingest
from autocut.settings import SettingsError
from autocut.transcribe.step import run_transcribe
from tests.test_transcribe import Api, fake_extract, project  # noqa: F401 (fixture)


def _prepare(project, transcribe=True):  # noqa: F811
    raw, root, probe = project
    run_ingest("reel", raw, projects_root=root, probe_fn=probe)
    if transcribe:
        run_transcribe(
            "reel", projects_root=root, api_key="k", client=Api().client(), extract_fn=fake_extract
        )
    return root


def test_cuts_write_segments_and_stats(project):  # noqa: F811
    root = _prepare(project)
    tl = run_cuts("reel", projects_root=root).timeline
    # profilo short (verticale): soglia 800, margine 150; camera 182340 ms
    assert [(s.id, s.state) for s in tl.segments] == [
        ("gap:^-w000001", "remove"),
        ("seg:w000001-w000002", "keep"),
        ("gap:w000002-w000003", "remove"),
        ("seg:w000003-w000004", "keep"),
        ("gap:w000004-$", "remove"),
    ]
    assert tl.stats is not None
    assert tl.stats.raw_ms == 182340
    assert tl.stats.kept_ms + tl.stats.removed_ms == tl.stats.raw_ms
    assert "cuts" in tl.run.steps


def test_set_changes_threshold_and_is_recorded(project):  # noqa: F811
    root = _prepare(project)
    tl = run_cuts("reel", projects_root=root, sets=["pauses.threshold_ms=5000"]).timeline
    assert tl.settings.pauses.threshold_ms == 5000
    assert [s.id for s in tl.segments if s.state == "remove"] == ["gap:w000004-$"]


def test_set_cannot_touch_transcription_model(project):  # noqa: F811
    root = _prepare(project)
    with pytest.raises(SettingsError, match="non si può cambiare"):
        run_cuts("reel", projects_root=root, sets=["transcription.model=altro"])


def test_cuts_are_deterministic(project):  # noqa: F811
    root = _prepare(project)
    a = run_cuts("reel", projects_root=root).timeline_path.read_bytes()
    b = run_cuts("reel", projects_root=root).timeline_path.read_bytes()
    assert a == b


def test_needs_transcription(project):  # noqa: F811
    root = _prepare(project, transcribe=False)
    with pytest.raises(CutsError, match="lancia prima transcribe"):
        run_cuts("reel", projects_root=root)


def test_retranscribing_clears_segments(project):  # noqa: F811
    root = _prepare(project)
    run_cuts("reel", projects_root=root)
    tl = run_transcribe("reel", projects_root=root, extract_fn=fake_extract).timeline
    assert tl.segments == [] and "cuts" not in tl.run.steps
