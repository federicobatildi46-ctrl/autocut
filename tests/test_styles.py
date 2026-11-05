"""Preset di stile, combinazione brand × stile e preparazione del render (senza Remotion)."""

import json

import pytest

from autocut.brands import BRANDS_DIR, load_brand
from autocut.models.timeline import Timeline
from autocut.overrides.resolve import EffectiveRange, effective_ranges
from autocut.render.captions import TimedWord, build_chunks, emphasis_index
from autocut.render.preview import (
    Piece,
    SoundEvent,
    build_props,
    hook_lines,
    pieces_in_window,
    plan_sounds,
    sound_events,
    to_out,
)
from autocut.styles import (
    STYLES_DIR,
    StyleError,
    StylePreset,
    list_styles,
    load_style,
    resolve_look,
)


def _federico():
    return load_brand(BRANDS_DIR / "federico" / "brand.json")


def _style(name: str) -> dict:
    return json.loads((STYLES_DIR / name / "style.json").read_text(encoding="utf-8"))


def test_repo_styles_are_valid():
    assert [s.id for s in list_styles()] == ["premium", "viral"]


def test_unknown_sound_or_font_is_rejected():
    bad = _style("viral")
    bad["sound"]["events"]["caption"] = "texture.non_esiste"
    with pytest.raises(ValueError, match="non presente nella libreria"):
        StylePreset.model_validate(bad)
    bad = _style("viral")
    bad["captions"]["font"] = "manca"
    with pytest.raises(ValueError, match="non definito in fonts"):
        StylePreset.model_validate(bad)


def test_folder_must_match_id(tmp_path):
    (tmp_path / "altro").mkdir()
    (tmp_path / "altro" / "style.json").write_text(json.dumps(_style("premium")), encoding="utf-8")
    with pytest.raises(StyleError, match="diverso dalla cartella"):
        list_styles(tmp_path)


def test_premium_uses_brand_fonts_and_emphasis():
    look = resolve_look(
        load_style(STYLES_DIR / "premium" / "style.json"), _federico(), portrait=True
    )
    cap = look["captions"]
    assert cap["font"] == "Inter" and cap["stroke_px"] == 0 and cap["animation"] == "blur_in"
    # parola chiave bold come nel reference Belfort, nel colore del brand
    e = cap["emphasis"]
    assert e["font"] == "Inter Tight" and e["weight"] == 800 and not e["italic"]
    assert e["color"] == "#F6B25A" and e["layout"] == "line" and e["scale"] == 2.4
    assert cap["size_pct"] == pytest.approx(5.6) and cap["bottom_pct"] == 38
    h = look["hook"]
    assert h["font"] == "Inter" and h["big_font"] == "Inter Tight" and h["animation"] == "reveal"
    assert h["colors"]["big"] == "#F6B25A" and h["center_pct"] == 60
    assert look["lower_third"]["name"] == "Federico Batildi"
    assert look["pacing"]["punch_in"]["mode"] == "phrase_alternate"
    assert (
        "contrast(1.08)" in look["grade"]["css_filter"]
        and "sepia(0.12)" in look["grade"]["css_filter"]
    )


def test_viral_overrides_font_and_cycles_brand_colors():
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), _federico(), portrait=True)
    cap = look["captions"]
    # sottotitoli piccoli e bassi come CRABBOX, parola chiave nel colore del brand
    assert cap["font"] == "Lilita One" and cap["case"] == "lower" and cap["stroke_px"] > 0
    assert cap["bottom_pct"] == 30 and cap["size_pct"] == pytest.approx(4.2)
    assert cap["colors"] == ["#FFFFFF"] and cap["max_words"] == 3
    assert cap["emphasis"]["color"] == "#F6B25A" and cap["emphasis"]["layout"] == "inline"
    h = look["hook"]
    assert h["colors"] == {"kicker": "#F6B25A", "big": "#FFFFFF", "sub": "#FFFFFF"}
    assert h["big_stroke_color"] == "#F6B25A" and h["center_pct"] == 63
    assert look["lower_third"] is None
    assert "Lilita+One" in look["fonts_url"] and "Inter" in look["fonts_url"]


def test_style_without_brand_still_resolves():
    look = resolve_look(load_style(STYLES_DIR / "premium" / "style.json"), None, portrait=True)
    assert look["brand"] is None and look["captions"]["colors"] == ["#FFFFFF"]


def test_chunks_and_emphasis_match_editor_rules():
    words = [TimedWord(t, i * 300, i * 300 + 250) for i, t in enumerate(
        "voglio andarmene in Thailandia. Prima".split())]  # fmt: skip
    chunks = build_chunks(words, 4, 24)
    # come nell'editor: la punteggiatura chiude la frase solo da 2 parole in su
    assert [c.text for c in chunks] == ["voglio andarmene in", "Thailandia. Prima"]
    assert emphasis_index(["ho", "25", "anni"]) == 1
    assert emphasis_index(["e", "per", "farli"]) == -1  # parola debole: meglio niente


def _eff():
    return [
        EffectiveRange(0, 1000, "remove", "a", "proposal"),
        EffectiveRange(1000, 2000, "keep", "b", "proposal"),
        EffectiveRange(2000, 2500, "remove", "c", "proposal"),
        EffectiveRange(2500, 4000, "keep", "d", "proposal"),
    ]


def test_window_pieces_skip_cuts_and_map_time():
    pieces = pieces_in_window(_eff(), 1500, 3500)
    assert [(p.src_start, p.src_end, p.out_start) for p in pieces] == [
        (1500, 2000, 0),
        (2500, 3500, 500),
    ]
    assert to_out(pieces, 2600) == 600 and to_out(pieces, 2200) is None


def _viral_look():
    return resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), _federico(), portrait=True)


def test_sounds_are_relative_to_voice_spaced_and_peak_aligned():
    look = _viral_look()  # voce -14 LUFS, texture -17 dB, whoosh -16 dB, spazio minimo 1200 ms
    cat = {
        "texture.pop": [
            {"file": "p1.mp3", "family": "textures", "peak_ms": 30, "level_db": -6.5},
            {"file": "p2.mp3", "family": "textures", "peak_ms": 20, "level_db": -6.5},
        ],
        "whoosh.short": [{"file": "w.mp3", "family": "whooshes", "peak_ms": 200, "level_db": -12}],
    }  # fmt: skip
    loud = {"p1.mp3": -15.0, "p2.mp3": -15.0, "w.mp3": -20.0}
    events = [
        SoundEvent(0, "emphasis", "a"),
        SoundEvent(1000, "emphasis", "troppo vicino: salta"),
        SoundEvent(1500, "card_in", "pop-up"),
        SoundEvent(3000, "cut", "blocco"),
    ]
    out = plan_sounds(look, events, cat, loudness=lambda s: loud[s["file"]])
    assert [(s["file"], s["event_ms"], s["from_ms"]) for s in out] == [
        ("p1.mp3", 0, 0), ("p2.mp3", 1500, 1480), ("w.mp3", 3000, 2800)]  # fmt: skip
    # pop: -14 - 17 = -31 LUFS voluti, il file è -15 -> -16 dB
    assert out[0]["gain_db"] == -16.0 and out[0]["volume"] == pytest.approx(0.1585, abs=1e-3)
    assert out[2]["gain_db"] == -10.0  # whoosh: -30 voluti, file -20


def test_more_important_event_wins_when_too_close():
    cat = {"texture.pop": [{"file": "p.mp3", "family": "textures", "peak_ms": 0, "level_db": -6.5}]}
    events = [SoundEvent(0, "emphasis", "parola"), SoundEvent(400, "card_in", "pop-up")]
    out = plan_sounds(_viral_look(), events, cat)
    assert [(s["kind"], s["event_ms"]) for s in out] == [("card_in", 400)]


def test_sound_events_only_on_key_moments():
    look = _viral_look()
    pieces = [Piece(0, 1000, 0), Piece(1500, 2500, 1000), Piece(5000, 6000, 2000)]
    captions = [
        {"from_ms": 100, "to_ms": 600, "emphasis": -1,
         "words": [{"text": "e poi", "from_ms": 100}]},
        {"from_ms": 2100, "to_ms": 2600, "emphasis": 1,
         "words": [{"text": "in", "from_ms": 2100}, {"text": "Thailandia.", "from_ms": 2300}]},
    ]  # fmt: skip
    cards = [
        {"from_ms": 0, "title": "Bali", "sound": True},
        {"from_ms": 1800, "title": "", "sound": False},
    ]
    ev = sound_events(look, None, captions, cards, pieces)
    got = sorted((e.kind, e.at_ms) for e in ev)
    # niente suono sulla frase senza parola chiave, né sul jump cut da 0,5 s, né sul pop-up muto
    assert got == [("card_in", 67), ("cut", 2000), ("emphasis", 2100)]
    assert any("Thailandia" in e.reason for e in ev)

    premium = resolve_look(
        load_style(STYLES_DIR / "premium" / "style.json"), _federico(), portrait=True
    )
    ev = sound_events(premium, {"lines": []}, captions, [], pieces)
    kinds = {e.kind: e.at_ms for e in ev}
    assert kinds["hook"] == 333  # la riga grande inizia a vedersi dopo ~10 fotogrammi
    assert kinds["emphasis"] == 2300 + 100  # entrata sfocata: a metà dissolvenza della parola


def test_build_props_on_fixture(timeline_dict, tmp_path):
    tl = Timeline.model_validate(timeline_dict)
    look = resolve_look(
        load_style(STYLES_DIR / "viral" / "style.json"), _federico(), portrait=False
    )
    props, pieces = build_props(
        project_dir=tmp_path, tl=tl, eff=effective_ranges(tl, None), look=look,
        window=(1000, 4200), source_rel="render/src.mp4", hook_text="RIGA UNO|riga due", catalog={},
    )  # fmt: skip
    assert props["width"] == 1920 and props["height"] == 1080  # fixture orizzontale
    # la falsa partenza (presa non scelta del gruppo di ripetizioni) resta fuori
    assert [(p["from_ms"], p["src_ms"]) for p in props["video"]["pieces"]] == [
        (0, 50),
        (150, 600),
        (300, 1950),
    ]
    assert props["durationInFrames"] == round(1550 / 1000 * 30)
    assert props["hook"] == {
        "lines": [{"text": "RIGA UNO", "role": "kicker"}, {"text": "riga due", "role": "big"}],
        "to_ms": 3000,
    }
    # l'hook è la copertina: le frasi dette durante i primi 3 s non diventano sottotitoli
    assert props["captions"] == []
    assert props["cards"] == [] and props["lowerThird"] is None and props["sounds"] == []

    props, _ = build_props(
        project_dir=tmp_path, tl=tl, eff=effective_ranges(tl, None), look=look,
        window=(1000, 4200), source_rel="render/src.mp4", hook_text=None, catalog={},
    )  # fmt: skip
    assert props["hook"] is None
    caps = props["captions"]
    assert [" ".join(w["text"] for w in c["words"]) for c in caps] == ["Ciao a tutti"]
    assert caps[0]["from_ms"] == 300 + 3100 - 2950 and caps[0]["color"] == "#FFFFFF"


def test_hook_line_roles():
    assert [x["role"] for x in hook_lines("solo")] == ["big"]
    assert [x["role"] for x in hook_lines("a|b|c")] == ["kicker", "big", "sub"]
    lines = hook_lines("a|b|*GRANDE*")
    assert lines[2] == {"text": "GRANDE", "role": "big"} and lines[1]["role"] == "kicker"


def test_keyword_sounds_are_rare():
    look = _viral_look()  # una parola chiave ogni 6 s, mai a meno di 2 s da un pop-up
    pieces = [Piece(0, 30000, 0)]

    def cap(at):
        return {
            "from_ms": at,
            "to_ms": at + 500,
            "emphasis": 0,
            "words": [{"text": "Thailandia", "from_ms": at}],
        }

    captions = [cap(1000), cap(4000), cap(8000), cap(15000)]
    cards = [{"from_ms": 14000, "title": "", "sound": True}]
    ev = [(e.kind, e.at_ms) for e in sound_events(look, None, captions, cards, pieces)]
    assert [x for x in ev if x[0] == "emphasis"] == [("emphasis", 1000), ("emphasis", 8000)]
