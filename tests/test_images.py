"""Pannello Immagini: ricerca, scontorno, foto nel video (niente rete né modelli veri)."""

import io
import json

import pytest
from PIL import Image

from autocut import images as imgs
from autocut.models.timeline import Timeline
from autocut.overrides.resolve import effective_ranges
from autocut.render.preview import build_props
from autocut.styles import STYLES_DIR, load_style, resolve_look

from .test_editor_server import SyncExecutor, make_client


def _png(size=(200, 300), square=(50, 80, 150, 220), alpha=False) -> bytes:
    """Sfondo bianco con un rettangolo rosso (la «persona»)."""
    im = Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else "white")
    im.paste((220, 30, 30, 255) if alpha else (220, 30, 30), square)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def fake_masker(im, progress=None, quality="fast"):
    """Maschera = i pixel rossi (come farebbe il modello con la persona)."""
    if progress:
        progress("cutting", None)
    g = im.convert("RGB").getchannel("G")  # rosso: G basso; bianco: G alto
    return Image.eval(g, lambda v: 255 if v < 100 else 0)


@pytest.mark.parametrize(
    ("ask", "query"),
    [
        ("trovami delle immagini di Francesco Totti", "Francesco Totti"),
        ("Totti", "Totti"),
        ("immagini scontornate di Del Piero", "Del Piero"),  # «Del» fa parte del nome
        ("un'immagine di Messi", "Messi"),
        ("mi trovi una foto della Ferrari?", "Ferrari"),
        ("cerca Lamborghini Urus", "Lamborghini Urus"),
    ],
)
def test_clean_query(ask, query):
    assert imgs.clean_query(ask) == query


def test_prepare_cuts_out_and_trims(tmp_path):
    dest = tmp_path / "images" / "img_0001.png"
    info = imgs.prepare(_png(), dest, masker=fake_masker)
    out = Image.open(dest)
    assert info == {"width": out.width, "height": out.height, "cutout": True, "quality": "fast"}
    assert out.mode == "RGBA" and 100 <= out.width <= 106 and 140 <= out.height <= 146  # figura
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255
    assert (tmp_path / "images" / "src" / "img_0001.png").is_file()  # originale per rifarlo
    imgs.prepare(imgs.original(dest), dest, cutout=False, masker=fake_masker)
    assert Image.open(dest).size == (200, 300)  # foto intera


def test_already_transparent_png_skips_the_model(tmp_path):
    def boom(*a, **k):
        raise AssertionError("il modello non serve")

    info = imgs.prepare(_png(alpha=True), tmp_path / "x.png", masker=boom)
    assert info["cutout"] is True and info["quality"] is None
    with pytest.raises(imgs.ImageError):
        imgs.prepare(b"non sono un'immagine", tmp_path / "y.png", masker=boom)
    with pytest.raises(imgs.ImageError):
        imgs.prepare(_png(), tmp_path / "z.png", quality="boh", masker=boom)


def _client(tmp_path):
    calls = []

    def search(q, *, transparent, free):
        calls.append((q, transparent, free))
        return [{"url": "https://x.it/totti.jpg", "thumb": "https://t/1", "page": "https://x.it",
                 "title": "Totti", "source": "x.it", "license": None}]  # fmt: skip

    def fetch(url, *, referer="", fallback=None):
        calls.append(("fetch", url, referer, fallback))
        return _png()

    c, pdir = make_client(
        tmp_path, image_search=search, image_fetch=fetch, image_masker=fake_masker,
        image_runner=lambda fn, *a: SyncExecutor().submit(fn, *a),
    )  # fmt: skip
    return c, pdir, calls


def test_search_add_place_and_redo(tmp_path):
    c, pdir, calls = _client(tmp_path)
    r = c.get("/api/images/search", params={"q": "trovami foto di Totti", "free": True}).json()
    assert r["query"] == "Totti" and r["results"][0]["source"] == "x.it"
    assert calls[-1] == ("trovami foto di Totti", False, True)
    assert c.get("/api/images/search", params={"q": " "}).status_code == 400

    res = r["results"][0]
    job = c.post("/api/images/add", json={**res, "cutout": True}).json()
    assert calls[-1] == ("fetch", res["url"], res["page"], res["thumb"])
    assert c.get(f"/api/images/job/{job['id']}").json()["status"] == "done"
    job = c.get(f"/api/images/job/{job['id']}").json()
    assert job["image"] == "images/img_0001.png" and job["cutout"] is True
    assert c.get("/media/images/img_0001.png").status_code == 200
    assert c.get("/media/images/..%2Fproxy.mp4").status_code == 404

    p = c.get("/api/project").json()
    assert p["images"][0]["image"] == "images/img_0001.png" and p["images"][0]["source"] == "x.it"
    p = c.post("/api/popups/add", json={"kind": "image", "image": job["image"], "cutout": True,
                                         "at_ms": 1500, "x_pct": 50, "y_pct": 76,
                                         "size": "large", "sound": False}).json()  # fmt: skip
    pop = next(x for x in p["popups"] if x["id"] == p["added"])
    assert pop["cutout"] is True and pop["sound"] is False and pop["placement"] == "free"
    assert pop["image_url"].startswith("/media/images/img_0001.png?v=")
    bad = {"kind": "image", "image": "../timeline.json", "at_ms": 0}
    assert c.post("/api/popups/add", json=bad).status_code == 404

    job = c.post("/api/images/add", json={"redo": "images/img_0001.png", "cutout": False}).json()
    assert job["status"] == "done" and job["cutout"] is False
    assert Image.open(pdir / "work" / "images" / "img_0001.png").size == (200, 300)
    meta = json.loads((pdir / "work" / "images" / "index.json").read_text(encoding="utf-8"))
    assert meta["img_0001.png"]["source"] == "x.it"  # la provenienza resta
    assert c.post("/api/images/add", json={"redo": "images/nope.png"}).status_code == 404
    assert c.post("/api/images/add", json={"url": "https://x", "quality": "x"}).status_code == 400
    assert c.post("/api/images/add", json={}).status_code == 400


def test_upload_from_pc_and_errors(tmp_path):
    import base64

    c, _, _ = _client(tmp_path)
    data = "data:image/png;base64," + base64.b64encode(_png()).decode()
    job = c.post("/api/images/add", json={"data": data, "title": "mia.png"}).json()
    assert job["status"] == "done" and job["image"] == "images/img_0001.png"
    job = c.post("/api/images/add", json={"data": "data:image/png;base64,AAAA"}).json()
    assert job["status"] == "error" and "immagine" in job["error"]
    assert c.get("/api/images/job/img999").status_code == 404


def test_render_card_for_cutout(timeline_dict, tmp_path):
    tl = Timeline.model_validate(timeline_dict)
    (tmp_path / "popups.json").write_text(json.dumps({"version": 1, "items": [{
        "id": "pop_0001", "at_ms": 3000, "duration_ms": 2000, "kind": "image",
        "image": "images/img_0001.png", "cutout": True, "placement": "free",
        "x_pct": 50, "y_pct": 76, "status": "approved", "size": "large", "style": "viral",
    }], "seeded_styles": ["viral"]}), encoding="utf-8")  # fmt: skip
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    props, _ = build_props(
        project_dir=tmp_path, tl=tl, eff=effective_ranges(tl, None), look=look,
        window=(1000, 4200), source_rel="render/src.mp4", hook_text=None, catalog={},
    )  # fmt: skip
    card = props["cards"][0]
    assert card["src"] == "images/img_0001.png" and card["cutout"] is True
    assert card["title"] == ""  # niente etichetta automatica sulle foto scontornate
