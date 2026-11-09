"""Pannello Filtri ed Esporta video (render finto)."""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from autocut import covers as cov
from autocut import filters as flt
from autocut.styles import STYLES_DIR, load_style, resolve_look

from .test_editor_server import make_client


def test_filters_presets_and_sliders_change_the_grade():
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    d = flt.update(flt.FiltersFile(), "viral", preset="bw")
    d = flt.update(d, "viral", values={"brightness": 1.1})
    g = flt.apply_to_look(look, flt.for_style(d, "viral"))["grade"]
    assert g["grayscale"] == 1 and g["brightness"] == 1.1 and "grayscale(1)" in g["css_filter"]
    assert (
        flt.apply_to_look(look, flt.StyleFilters())["grade"]["css_filter"]
        == look["grade"]["css_filter"]
    )  # «Originale dello stile» non cambia niente
    with pytest.raises(flt.FilterError):
        flt.update(d, "viral", preset="boh")
    with pytest.raises(flt.FilterError):
        flt.update(d, "viral", values={"brightness": 9})
    with pytest.raises(flt.FilterError):
        flt.update(d, "viral", values={"bogus": 1})


def test_filters_api_and_undo(tmp_path):
    c, _ = make_client(tmp_path)
    assert c.post("/api/filters", json={"preset": "vivid"}).status_code == 400  # serve uno stile
    c.post("/api/style", json={"id": "viral"})
    p = c.post("/api/filters", json={"preset": "vivid"}).json()
    assert p["filters"]["preset"] == "vivid" and p["style"]["grade"]["saturation"] == 1.45
    p = c.post("/api/filters", json={"values": {"warmth": 0.2}}).json()
    assert p["style"]["grade"]["warmth"] == 0.2
    p = c.post("/api/history/undo").json()
    assert p["style"]["grade"]["warmth"] != 0.2  # Annulla vale anche per i filtri
    p = c.post("/api/filters", json={"reset": True}).json()
    assert p["filters"]["preset"] == "style"


def _png(path):
    buf = io.BytesIO()
    Image.new("RGB", (9, 16), "red").save(buf, "PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())


def test_export_video_runs_and_serves_the_file(tmp_path):
    calls = []

    def runner(name, **kw):
        calls.append((name, kw))
        out = kw["projects_root"] / name / "renders" / "style-viral-0s.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 2048)
        return SimpleNamespace(output=out)

    c, pdir = make_client(tmp_path, export_runner=runner)
    assert c.post("/api/export/video").status_code == 400  # serve uno stile
    c.post("/api/style", json={"id": "viral"})
    p = c.post("/api/export/video").json()
    job = p["export"]["job"]
    assert job["status"] == "done", job
    assert calls[0][0] == "episodio-12" and calls[0][1]["at_ms"] == 0 and calls[0][1]["clip"]
    assert calls[0][1]["after_ms"] > 0  # tutto il video
    last = p["export"]["last"]
    assert last["name"].startswith("episodio-12-viral-finale-")
    assert c.get(last["url"]).status_code == 200
    assert c.get("/media/export/..%2Ftimeline.json").status_code == 404


def test_attach_cover_falls_back_to_plain_copy(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not really a video")
    cover = tmp_path / "c.png"
    _png(cover)
    out = cov.attach_cover(video, cover, tmp_path / "out" / "final.mp4")
    assert out.read_bytes() == b"not really a video"  # ffmpeg non ce la fa: copia semplice
    assert cov.attach_cover(video, None, tmp_path / "o2.mp4").exists()
