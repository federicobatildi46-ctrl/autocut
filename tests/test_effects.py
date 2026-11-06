"""Pannello Effetti: animazioni di testo/sticker, transizioni alle giunte, proposta di Claude."""

import pytest

from autocut import effects as fx
from autocut.models.timeline import Timeline
from autocut.overrides.resolve import EffectiveRange, effective_ranges
from autocut.render.preview import Piece, _transitions, build_props
from autocut.styles import STYLES_DIR, load_style, resolve_look

from .test_editor_server import make_client


def _r(a, b, state, sid):
    return EffectiveRange(start_ms=a, end_ms=b, state=state, source_id=sid, origin="proposal")


def test_galleries_differ_per_style_and_text_only_effects():
    viral = {a["id"] for a in fx.ANIMS if a["phase"] == "in" and "viral" in a["sets"]}
    premium = {a["id"] for a in fx.ANIMS if a["phase"] == "in" and "premium" in a["sets"]}
    assert {"pop", "bounce", "spin_in"} <= viral - premium  # d'impatto solo nel viral
    assert {"rise", "blur_in", "words_blur"} <= premium - viral  # morbidi solo nel premium
    assert "typewriter" in fx.anim_ids("in", text=True) and "typewriter" not in fx.anim_ids(
        "in", text=False
    )
    remotion = {t["id"] for t in fx.TRANSITIONS if t["source"] == "remotion"}
    assert {"fade", "slide_left", "wipe_left", "cube", "iris", "clock_wipe"} <= remotion


def test_update_resolve_and_reset():
    d = fx.update(
        fx.EffectsFile(), "viral", target="captions", phase="in", spec={"type": "bounce", "ms": 400}
    )
    d = fx.update(d, "viral", target="sticker", item="pop_0001", phase="loop",
                  spec={"type": "wiggle", "ms": 0, "speed": 2})  # fmt: skip
    d = fx.update(d, "viral", target="transition", item="gap:a-b", spec={"type": "whip", "ms": 300})
    r = fx.resolved("viral", fx.for_style(d, "viral"))
    assert r["captions"]["in"]["type"] == "bounce" and r["captions"]["out"]["type"] == "none"
    assert r["stickers"]["pop_0001"]["loop"]["speed"] == 2
    assert r["stickers"]["pop_0001"]["in"]["type"] == "pop"  # il resto dal predefinito
    assert fx.sticker_anim(r, "pop_9999") == r["sticker_default"]
    assert r["transitions"]["gap:a-b"]["type"] == "whip"
    assert fx.for_style(d, "premium").captions.in_ is None  # stili separati
    d = fx.update(d, "viral", target="captions", phase="in", spec=None)
    assert fx.resolved("viral", fx.for_style(d, "viral"))["captions"]["in"]["type"] == "pop"


def test_update_rejects_bad_effects():
    with pytest.raises(fx.EffectsError):
        fx.update(
            fx.EffectsFile(),
            "viral",
            target="captions",
            phase="loop",
            spec={"type": "float", "ms": 0},
        )
    with pytest.raises(fx.EffectsError):
        fx.update(fx.EffectsFile(), "viral", target="sticker", item="x", phase="in",
                  spec={"type": "typewriter", "ms": 300})  # fmt: skip
    with pytest.raises(fx.EffectsError):
        fx.update(
            fx.EffectsFile(),
            "viral",
            target="transition",
            item="x",
            spec={"type": "boh", "ms": 300},
        )


def test_default_transitions_follow_cut_kind():
    r = fx.resolved("viral", fx.StyleEffects())
    assert fx.transition_for(r, {"id": "a", "kind": "scene"})["type"] == "whip"
    assert fx.transition_for(r, {"id": "b", "kind": "cut", "block": True})["type"] == "zoom"
    assert (
        fx.transition_for(r, {"id": "c", "kind": "cut", "block": False}) is None
    )  # jump cut: netto
    p = fx.resolved("premium", fx.StyleEffects())
    assert fx.transition_for(p, {"id": "a", "kind": "scene"})["type"] == "blur"


def test_boundaries_cuts_and_cache(tmp_path, timeline_dict):
    tl = Timeline.model_validate(timeline_dict)
    eff = [
        _r(0, 1000, "keep", "seg:a"),
        _r(1000, 3000, "remove", "gap:a-b"),
        _r(3000, 5000, "keep", "seg:b"),
    ]
    pts = fx.boundaries(tl, eff, video=None, offset_ms=0, cache_path=tmp_path / "scenes.json")
    assert [(b["id"], b["kind"], b["block"], b["gap_ms"]) for b in pts] == [
        ("gap:a-b", "cut", True, 2000)
    ]
    (tmp_path / "scenes.json").write_text(
        '{"diffs": {"1000-3000": 40.0}, "scenes": [4000]}', encoding="utf-8"
    )
    pts = fx.boundaries(tl, eff, video=None, offset_ms=0, cache_path=tmp_path / "scenes.json")
    assert [(b["id"], b["kind"]) for b in pts] == [("gap:a-b", "scene"), ("scene:4000", "scene")]


def test_transitions_need_handles():
    pieces = [Piece(0, 1000, 0), Piece(3000, 3100, 1000), Piece(3100, 6000, 1100)]
    points = [{"id": "gap:a-b", "at_ms": 1000, "end_ms": 3000, "kind": "scene", "block": True}]
    r = fx.resolved("viral", fx.StyleEffects())
    out = _transitions(pieces, points, r, src_len=6000)
    # il pezzo dopo dura solo 100 ms: la transizione si accorcia a quanto si può
    assert out == [{"join": 0, "at_ms": 1000, "type": "whip", "ms": 100, "point": "gap:a-b"}]


def test_build_props_carries_effects(timeline_dict, tmp_path):
    tl = Timeline.model_validate(timeline_dict)
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    eff = effective_ranges(tl, None)
    res = fx.resolved("viral", fx.StyleEffects())
    res["captions"]["in"] = {"type": "bounce", "ms": 400, "speed": 1.0}
    props, _ = build_props(
        project_dir=tmp_path, tl=tl, eff=eff, look=look, window=(1000, 4200),
        source_rel="render/src.mp4", hook_text=None, catalog={}, effects=res, points=[],
    )  # fmt: skip
    assert props["look"]["captions"]["anim"]["in"]["type"] == "bounce"
    assert props["transitions"] == []


def test_effects_api_and_claude_suggestion(tmp_path):
    c, pdir = make_client(tmp_path)
    pop = {"target": "captions", "phase": "in", "spec": {"type": "pop", "ms": 300}}
    assert c.post("/api/effects", json=pop).status_code == 400  # serve uno stile
    c.post("/api/style", json={"id": "premium"})
    p = c.get("/api/project").json()
    assert (
        p["effects"]["style"] == "premium"
        and p["effects"]["resolved"]["captions"]["in"]["type"] == "words_blur"
    )
    p = c.post(
        "/api/effects",
        json={"target": "captions", "phase": "in", "spec": {"type": "rise", "ms": 500}},
    ).json()
    assert p["effects"]["resolved"]["captions"]["in"] == {"type": "rise", "ms": 500, "speed": 1.0}
    long = {"target": "captions", "phase": "in", "spec": {"type": "rise", "ms": 99999}}
    assert c.post("/api/effects", json=long).status_code == 400

    c.fake_agent.json_reply = {
        "captions": {
            "in": {"type": "fade", "ms": 400},
            "out": {"type": "spin_out", "ms": 300},
        },  # spin_out: non premium
        "transitions": {"inesistente": {"type": "blur", "ms": 500}},
        "message": "Morbido ed elegante",
    }
    p = c.post("/api/effects/suggest").json()
    caps = p["effects"]["resolved"]["captions"]
    assert (
        caps["in"]["type"] == "fade" and caps["out"]["type"] == "fade"
    )  # l'uscita non valida è scartata
    assert p["effects"]["resolved"]["transitions"] == {} and p["message"] == "Morbido ed elegante"
    assert p["effects"]["resolved"]["suggested"] is True
    assert (pdir / "effects.json").exists()
    assert c.get("/anim.js").status_code == 200
