"""Pannello Testo: scelte salvate per stile, applicate al look e al render."""

import json

import pytest

from autocut import text_style as txt
from autocut.brands import BRANDS_DIR, load_brand
from autocut.models.timeline import Timeline
from autocut.overrides.resolve import effective_ranges
from autocut.render.preview import build_props
from autocut.styles import STYLES_DIR, load_style, resolve_look

from .test_editor_server import make_client


def _look(style="viral"):
    brand = load_brand(BRANDS_DIR / "federico" / "brand.json")
    return resolve_look(load_style(STYLES_DIR / style / "style.json"), brand, portrait=True)


def test_catalog_has_a_dozen_fonts_per_preset_with_real_weights():
    for sid in ("viral", "premium"):
        fonts = txt.catalog_payload(sid)["fonts"]
        assert len(fonts) >= 12 and all(f["set"] == sid for f in fonts)
        assert txt.catalog_payload(sid)["fonts_url"].startswith(
            "https://fonts.googleapis.com/css2?"
        )
    kinds = {f["kind"] for f in txt.catalog_payload("premium")["fonts"]}
    assert {"serif", "sans"} <= kinds  # per mischiare un serif con un sans
    assert len(txt.catalog_payload(None)["fonts"]) == len(txt.CATALOG)


def test_update_base_and_scene_per_style(tmp_path):
    allowed = txt.allowed_fonts(_look())
    data = txt.update(txt.TextStyleFile(), "viral", scene=None,
                      fields={"font": "Anton", "preset": "box"}, allowed=allowed)  # fmt: skip
    scene = {"text": "Nuovo testo", "color": "#FFD60A"}
    data = txt.update(data, "viral", scene="w000003", fields=scene, allowed=allowed)
    txt.save(tmp_path, data)
    back = txt.load(tmp_path)
    assert txt.for_style(back, "viral").base.font == "Anton"
    assert txt.for_style(back, "viral").scenes["w000003"].text == "Nuovo testo"
    assert txt.for_style(back, "premium").base.font is None  # ogni stile ha le sue scelte
    raw = json.loads((tmp_path / txt.TEXT_FILE).read_text(encoding="utf-8"))
    assert "x_pct" not in raw["styles"]["viral"]["base"]  # niente campi vuoti nel file

    # None = torna al valore dello stile; scena vuota = sparisce
    back = txt.update(back, "viral", scene=None, fields={"font": None}, allowed=allowed)
    assert txt.for_style(back, "viral").base.font is None
    back = txt.update(back, "viral", scene="w000003", fields={}, reset=True, allowed=allowed)
    assert txt.for_style(back, "viral").scenes == {}


def test_update_rejects_unknown_fonts_and_bad_values():
    allowed = txt.allowed_fonts(_look())
    with pytest.raises(txt.TextStyleError):
        txt.update(
            txt.TextStyleFile(), "viral", scene=None, fields={"font": "Comic Sans"}, allowed=allowed
        )
    with pytest.raises(ValueError):
        txt.update(
            txt.TextStyleFile(), "viral", scene=None, fields={"color": "rosso"}, allowed=allowed
        )
    with pytest.raises(ValueError):
        txt.update(txt.TextStyleFile(), "viral", scene=None, fields={"scale": 9}, allowed=allowed)


def test_caption_fields_presets_and_transform():
    base = _look()["captions"]
    box = txt.caption_fields(base, txt.CaptionStyle(preset="box", fx_color="#ff2d78"))
    assert box["effect"] == "box" and box["stroke_px"] == 0 and box["fx_color"] == "#FF2D78"
    glow = txt.caption_fields(base, txt.CaptionStyle(preset="glow"))
    assert glow["effect"] == "glow" and glow["fx_color"] == base["emphasis"]["color"]
    stroke = txt.caption_fields(base, txt.CaptionStyle(preset="stroke"))
    assert stroke["stroke_px"] >= 4 and stroke["effect"] == "none"
    moved = txt.caption_fields(base, txt.CaptionStyle(x_pct=5, y_pct=-20, scale=2, rotation=-12))
    assert (moved["x_pct"], moved["y_pct"], moved["scale"], moved["rotation"]) == (5, -20, 2, -12)
    mixed = txt.caption_fields(
        base, txt.CaptionStyle(font="Bangers", emph_font="Bebas Neue", bold=True)
    )
    assert mixed["font"] == "Bangers" and mixed["emphasis"]["font"] == "Bebas Neue"


def test_apply_to_look_loads_chosen_fonts():
    st = txt.StyleText(
        base=txt.CaptionStyle(font="Bangers"),
        scenes={"w1": txt.SceneEdit(emph_font="Playfair Display")},
    )
    look = txt.apply_to_look(_look(), st)
    assert look["captions"]["font"] == "Bangers"
    assert "family=Bangers" in look["fonts_url"] and "family=Playfair+Display" in look["fonts_url"]
    assert look["fonts_url"].count("display=swap") == 1
    assert _look()["captions"]["font"] != "Bangers"  # il look originale non cambia


def test_render_uses_scene_text_and_style(timeline_dict, tmp_path):
    tl = Timeline.model_validate(timeline_dict)
    ciao = [w.id for w in tl.words if w.text.startswith("Ciao")]  # c'è anche la falsa partenza
    look = txt.apply_to_look(_look(), txt.StyleText(base=txt.CaptionStyle(rotation=-8)))
    edit = txt.SceneEdit(text="Ciao 25 amici", color="#FFD60A", scale=1.5)
    scenes = dict.fromkeys(ciao, edit)
    props, _ = build_props(
        project_dir=tmp_path, tl=tl, eff=effective_ranges(tl, None), look=look,
        window=(1000, 4200), source_rel="render/src.mp4", hook_text=None, catalog={}, scenes=scenes,
    )  # fmt: skip
    cap = props["captions"][0]
    assert [w["text"] for w in cap["words"]] == ["Ciao", "25", "amici"]
    assert (
        cap["words"][0]["from_ms"] == cap["from_ms"]
    )  # le parole nuove stanno nei tempi della frase
    assert cap["emphasis"] == 1  # il numero diventa la parola chiave
    assert cap["color"] == "#FFD60A" and cap["style"]["scale"] == 1.5
    assert "rotation" not in cap["style"]  # quella vale per tutti: sta già nel look
    assert props["look"]["captions"]["rotation"] == -8


def test_text_api(tmp_path):
    c, pdir = make_client(tmp_path)
    assert (
        c.post("/api/text", json={"fields": {"font": "Anton"}}).status_code == 400
    )  # serve uno stile
    c.post("/api/brand", json={"id": "federico"})
    p = c.post("/api/style", json={"id": "premium"}).json()
    assert {f["set"] for f in p["text"]["fonts"]} == {"premium"}

    p = c.post("/api/text", json={"fields": {"font": "Playfair Display", "x_pct": 3}}).json()
    assert (
        p["style"]["captions"]["font"] == "Playfair Display"
        and p["style"]["captions"]["x_pct"] == 3
    )
    p = c.post(
        "/api/text", json={"scene": "w000001", "fields": {"text": "Ciao!", "italic": True}}
    ).json()
    assert p["text"]["scenes"]["w000001"] == {"italic": True, "text": "Ciao!"}
    assert p["text"]["resolved"]["w000001"] == {"italic": True}
    assert c.post("/api/text", json={"fields": {"font": "Papyrus"}}).status_code == 400
    assert json.loads((pdir / "text_style.json").read_text(encoding="utf-8"))["styles"]["premium"]

    p = c.post("/api/style", json={"id": "viral"}).json()  # Viral: font e scelte suoi
    assert {f["set"] for f in p["text"]["fonts"]} == {"viral"} and p["text"]["base"] == {}
