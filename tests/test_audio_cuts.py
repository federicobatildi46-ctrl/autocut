"""Timeline stile CapCut: tagli a mano, Annulla/Ripeti per tutto, pannello Audio."""

import json

import pytest

from autocut import audio_mix as amix
from autocut import manual_cuts as mc
from autocut.overrides.resolve import EffectiveRange
from autocut.render.preview import Piece, window_sounds

from .test_editor_server import GAP, make_client

CATALOG = {
    "whoosh.short": [{"id": "whoosh.short.01", "type": "whoosh.short", "family": "whooshes",
                      "label": "Short whoosh", "file": "whooshes/short/short_01.mp3",
                      "level_db": -12.0, "duration_ms": 900, "peak_ms": 200}],
    "texture.pop": [{"id": "texture.pop.01", "type": "texture.pop", "family": "textures",
                     "label": "Pop", "file": "textures/pop/pop_01.mp3",
                     "level_db": -6.5, "duration_ms": 400, "peak_ms": 20}],
}  # fmt: skip


def _r(a, b, state="keep", sid="seg:a", origin="proposal"):
    return EffectiveRange(a, b, state, sid, origin)


def test_manual_cuts_split_remove_restore():
    d = mc.split(mc.CutsFile(), 2000)
    with pytest.raises(mc.CutError):
        mc.split(d, 2010)  # già divisa lì
    d = mc.remove(d, 2000, 3000)
    eff = mc.apply([_r(0, 1000), _r(1000, 1500, "remove", "gap:x"), _r(1500, 5000)], d)
    assert [(r.start_ms, r.end_ms, r.state, r.origin) for r in eff] == [
        (0, 1000, "keep", "proposal"),
        (1000, 1500, "remove", "proposal"),
        (1500, 2000, "keep", "proposal"),
        (2000, 3000, "remove", "manual"),
        (3000, 5000, "keep", "proposal"),
    ]
    assert eff[3].source_id == "cut:2000-3000"
    d = mc.restore(d, 2000, 2500)
    assert d.removed == [(2500, 3000)]
    with pytest.raises(mc.CutError):
        mc.restore(d, 0, 100)
    assert mc.unsplit(d, 2100).splits == []


def test_audio_update_and_resolve():
    look = {"sound": {"voice_lufs": -14.0, "relative_db": {"whooshes": -18.0, "textures": -16.0}}}
    plan = [{"id": "auto:cut:3000", "type": "whoosh.short", "file": "whooshes/short/short_01.mp3",
             "kind": "cut", "reason": "cambio di blocco", "at_ms": 3000, "lead_ms": 200,
             "base_db": -20.0}]  # fmt: skip
    d = amix.update(amix.AudioFile(), "viral", target="mix", fields={"sfx_db": -3, "voice_db": 2})
    d = amix.update(d, "viral", target="sound", item="auto:cut:3000",
                    fields={"gain_db": 4, "shift_ms": 100}, catalog=CATALOG)  # fmt: skip
    d = amix.update(d, "viral", target="sound", item="auto:cut:3000", fields={"shift_ms": 100})
    d = amix.update(d, "viral", target="add", fields={"type": "texture.pop", "at_ms": 1000},
                    catalog=CATALOG)  # fmt: skip
    sa = amix.for_style(d, "viral")
    out = amix.resolve(plan, sa, look, CATALOG)
    auto = next(s for s in out if s["origin"] == "auto")
    user = next(s for s in out if s["origin"] == "user")
    assert auto["at_ms"] == 3200 and auto["offset_db"] == 4  # spostato due volte di 100 ms
    assert auto["gain_db"] == round(auto["base_db"] + 4 - 3, 1)
    assert user["id"] == "snd_0001" and user["lead_ms"] == 20 and out[0] is user
    assert amix.for_style(d, "premium") == amix.StyleAudio()  # stili separati
    with pytest.raises(amix.AudioError):
        amix.update(d, "viral", target="sound", item="auto:x", fields={"type": "boh"},
                    catalog=CATALOG)  # fmt: skip
    with pytest.raises(amix.AudioError):
        amix.update(d, "viral", target="mix", fields={"voice_db": 99})
    d = amix.update(d, "viral", target="mix", fields={"voice_muted": True})
    assert amix.voice_offset_db(amix.for_style(d, "viral")) == -80.0
    # nel render: muti e suoni nelle parti tagliate non suonano
    pieces = [Piece(0, 2000, 0), Piece(3000, 6000, 2000)]
    sounds = window_sounds(
        [*out, {**auto, "id": "x", "at_ms": 2500}, {**user, "id": "y", "muted": True}], pieces
    )
    assert [(s["type"], s["event_ms"]) for s in sounds] == [("texture.pop", 1000),
                                                             ("whoosh.short", 2200)]  # fmt: skip


def test_history_undo_redo_everything(tmp_path):
    c, pdir = make_client(tmp_path, sfx_catalog=CATALOG)
    c.post("/api/style", json={"id": "viral"})
    c.post("/api/decision", json={"id": GAP, "action": "flip"})
    c.post("/api/text", json={"fields": {"font": "Anton"}})
    p = c.post("/api/cuts", json={"action": "split", "ms": 4000}).json()
    assert p["cuts"]["splits"] == [4000] and p["summary"]["can_undo"] is True

    p = c.post("/api/history/undo").json()  # via la divisione
    assert p["cuts"]["splits"] == [] and p["summary"]["can_redo"] is True
    p = c.post("/api/history/undo").json()  # via il font
    assert p["style"]["captions"]["font"] != "Anton"
    p = c.post("/api/history/undo").json()  # via la scelta sul taglio (nuova voce, non riscritta)
    assert next(d for d in p["decisions"] if d["id"] == GAP)["effective"] == "remove"
    ov = json.loads((pdir / "overrides.json").read_text(encoding="utf-8"))
    assert [e["action"] for e in ov["history"]] == ["create", "remove"]
    p = c.post("/api/history/redo").json()
    assert next(d for d in p["decisions"] if d["id"] == GAP)["effective"] == "keep"
    p = c.post("/api/history/redo").json()
    assert p["style"]["captions"]["font"] == "Anton"
    c.post("/api/history/redo")
    assert c.post("/api/history/redo").status_code == 400  # niente da ripetere
    c.post("/api/history/undo")
    c.post("/api/text", json={"fields": {"font": "Bebas Neue"}})  # una modifica nuova
    assert c.get("/api/project").json()["summary"]["can_redo"] is False


def test_cuts_and_audio_api(tmp_path):
    c, pdir = make_client(tmp_path, sfx_catalog=CATALOG)
    p = c.post("/api/cuts", json={"action": "remove", "start": 3200, "end": 3600}).json()
    cut = [r for r in p["effective"] if r["origin"] == "manual"]
    assert [(r["start_ms"], r["end_ms"]) for r in cut] == [(3200, 3600)]
    assert p["summary"]["kept_ms"] < 5200
    p = c.post("/api/cuts", json={"action": "restore", "start": 3200, "end": 3600}).json()
    assert not any(r["origin"] == "manual" for r in p["effective"])
    assert c.post("/api/cuts", json={"action": "boh"}).status_code == 400
    assert c.post("/api/cuts", json={"action": "split"}).status_code == 400

    p = c.post("/api/audio", json={"target": "mix", "fields": {"voice_db": -4}}).json()
    assert p["audio"]["voice_db"] == -4 and p["audio"]["library"][0]["type"] == "texture.pop"
    add = {"target": "add", "fields": {"type": "whoosh.short", "at_ms": 3300}}
    p = c.post("/api/audio", json=add).json()
    snd = p["audio"]["sounds"][0]
    assert snd["id"] == "snd_0001" and snd["url"] == "/media/sfx/whooshes/short/short_01.mp3"
    p = c.post("/api/audio", json={"target": "remove", "item": "snd_0001"}).json()
    assert p["audio"]["sounds"] == []
    bad = {"target": "add", "fields": {"type": "boh", "at_ms": 0}}
    assert c.post("/api/audio", json=bad).status_code == 400
    assert c.get("/media/sfx/..%2F..%2Ftimeline.json").status_code == 404
    assert (pdir / "audio.json").exists()
