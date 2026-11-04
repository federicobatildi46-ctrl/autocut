"""Pause e segmenti con parole finte."""

import pytest

from autocut.cuts.pauses import compute_segments
from autocut.models import Timeline
from autocut.models.timeline import PauseSettings, Word
from autocut.settings import resolve_settings


def W(i: int, start: int, end: int, text: str = "x", kind: str = "word") -> Word:
    return Word(id=f"w{i:06d}", text=text, start_ms=start, end_ms=end, kind=kind)


TRANSCRIPTION = resolve_settings("long").transcription


def segs(words, *, thr=1000, margin=150, start=0, end=10000, transcription=TRANSCRIPTION):
    return compute_segments(
        words,
        axis_start_ms=start,
        axis_end_ms=end,
        pauses=PauseSettings(threshold_ms=thr, margin_ms=margin),
        transcription=transcription,
    )


def brief(segments):
    return [(s.id, s.state, s.start_ms, s.end_ms) for s in segments]


def test_matches_the_fixture_example(timeline_dict):
    tl = Timeline.model_validate(timeline_dict)
    out = segs(tl.words, end=tl.sources.camera.duration_ms)
    assert brief(out) == brief(tl.segments)


def test_segments_cover_the_whole_axis_contiguously():
    words = [W(1, 500, 900), W(2, 3000, 3500), W(3, 3600, 4000), W(4, 7000, 7400)]
    out = segs(words)
    assert out[0].start_ms == 0 and out[-1].end_ms == 10000
    assert all(a.end_ms == b.start_ms for a, b in zip(out, out[1:], strict=False))


def test_no_long_pause_means_single_keep():
    words = [W(1, 100, 500), W(2, 900, 1300)]
    assert brief(segs(words, end=1800)) == [("seg:w000001-w000002", "keep", 0, 1800)]


def test_threshold_is_inclusive():
    words = [W(1, 0, 1000), W(2, 2000, 2500)]  # pausa esattamente 1000 ms
    out = segs(words, end=2500)
    assert ("gap:w000001-w000002", "remove", 1150, 1850) in brief(out)
    out = segs(words, thr=1001, end=2500)
    assert all(s.state == "keep" for s in out)


def test_margins_are_left_on_both_sides():
    words = [W(1, 0, 1000), W(2, 3000, 3500)]
    gap = next(s for s in segs(words, end=3500) if s.state == "remove")
    assert (gap.start_ms, gap.end_ms) == (1150, 2850)
    assert gap.data == {"gap_ms": 2000, "threshold_ms": 1000, "margin_ms": 150}


def test_head_and_tail_have_no_outer_margin():
    words = [W(1, 2000, 2500)]
    assert brief(segs(words, end=6000)) == [
        ("gap:^-w000001", "remove", 0, 1850),
        ("seg:w000001-w000001", "keep", 1850, 2650),
        ("gap:w000001-$", "remove", 2650, 6000),
    ]


def test_margin_wider_than_gap_does_not_cut():
    words = [W(1, 0, 1000), W(2, 1250, 1500)]  # pausa 250 >= soglia 200, ma 2*150 > 250
    assert all(s.state == "keep" for s in segs(words, thr=200, end=1500))


def test_dead_event_counts_as_silence():
    words = [
        W(1, 0, 1000, "farmi"),
        W(2, 1050, 4400, "[esita]", "audio_event"),
        W(3, 4500, 5000, "Saluto"),
    ]
    out = segs(words, end=5000)
    gap = next(s for s in out if s.state == "remove")
    assert gap.id == "gap:w000001-w000003"  # ancorato alle parole, non all'evento
    assert (gap.start_ms, gap.end_ms) == (1150, 4350)
    assert gap.data["dead_events"] == [{"id": "w000002", "tag": "esita"}]
    assert "[esita]" in gap.reason


def test_laughter_protects_speech():
    words = [
        W(1, 0, 1000),
        W(2, 1000, 4000, "(risata)", "audio_event"),
        W(3, 4100, 5000),
    ]
    assert all(s.state == "keep" for s in segs(words, end=5000))


def test_ignore_makes_laughter_cuttable():
    t = TRANSCRIPTION.model_copy(update={"audio_events": "ignore"})
    words = [W(1, 0, 1000), W(2, 1000, 4000, "(risata)", "audio_event"), W(3, 4100, 5000)]
    out = segs(words, end=5000, transcription=t)
    assert [s.state for s in out] == ["keep", "remove", "keep"]


def test_overlapping_items_use_the_latest_end():
    words = [W(1, 0, 3000), W(2, 500, 800), W(3, 3500, 4000)]  # w2 dentro w1
    assert all(s.state == "keep" for s in segs(words, end=4000))


def test_no_speech_at_all():
    out = segs([W(1, 100, 900, "[esita]", "audio_event")], end=5000)
    assert brief(out) == [("gap:^-$", "remove", 0, 5000)]
    assert out[0].reason == "nessun parlato nel tratto"


def test_range_axis_uses_absolute_times():
    words = [W(1, 61500, 62000), W(2, 64000, 64500)]
    out = segs(words, start=60000, end=66000)
    assert brief(out) == [
        ("gap:^-w000001", "remove", 60000, 61350),
        ("seg:w000001-w000001", "keep", 61350, 62150),
        ("gap:w000001-w000002", "remove", 62150, 63850),
        ("seg:w000002-w000002", "keep", 63850, 64650),
        ("gap:w000002-$", "remove", 64650, 66000),
    ]


def test_ids_survive_threshold_changes():
    words = [W(1, 0, 1000), W(2, 3000, 3500), W(3, 3600, 4000)]
    a = {s.id for s in segs(words, thr=1000, end=4000) if s.state == "remove"}
    b = {s.id for s in segs(words, thr=1500, margin=100, end=4000) if s.state == "remove"}
    assert a == b == {"gap:w000001-w000002"}


def test_empty_axis_is_an_error():
    with pytest.raises(ValueError):
        segs([], start=100, end=100)
