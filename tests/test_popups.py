"""Pop-up: modello, operazioni (aggiungi/cambia/togli), proposte automatiche, API dell'editor."""

import json

import pytest

from autocut import popups as pops
from autocut.render.preview import _cards
from autocut.styles import STYLES_DIR, load_style, resolve_look

from .test_editor_server import client  # noqa: F401  (fixture)


def _done_request(pdir, time_ms=1200):
    (pdir / "ai_requests.json").write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "id": "ai_0001",
                        "time_ms": time_ms,
                        "status": "done",
                        "result": {
                            "media_type": "image",
                            "local": ["/media/ai/results/ai_0001-1.png"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_seed_turns_generated_images_into_proposals_once_per_style(tmp_path):
    _done_request(tmp_path)
    data = pops.seed_from_ai_requests(pops.PopupsFile(), tmp_path, "viral")
    assert data.seeded_styles == ["viral"] and len(data.items) == 1
    p = data.items[0]
    assert (p.id, p.kind, p.image, p.origin, p.status, p.style) == (
        "pop_0001", "image", "ai/results/ai_0001-1.png", "auto", "proposed", "viral")  # fmt: skip
    # un'altra copia per il premium: cambiarla lì non tocca il viral
    data = pops.seed_from_ai_requests(data, tmp_path, "premium")
    assert [x.style for x in data.items] == ["viral", "premium"]
    # una seconda volta non duplica (e se l'utente lo cancella non torna)
    gone = data.model_copy(update={"items": []})
    assert pops.seed_from_ai_requests(gone, tmp_path, "viral").items == []


def test_apply_ops_add_by_word_update_remove():
    data = pops.PopupsFile(seeded=True)
    words = {"w000003": 3100}
    data, log = pops.apply_ops(
        data,
        {
            "add": [
                {
                    "word_id": "w000003",
                    "kind": "emoji",
                    "emoji": "🌴",
                    "title": "MARE",
                    "reason": "r",
                }
            ]
        },
        "ai",
        words=words,
    )
    assert log == ["aggiunto pop_0001"] and data.items[0].at_ms == 3100
    data, _ = pops.apply_ops(
        data, {"update": [{"id": "pop_0001", "sound": False, "origin": "x"}]}, "user"
    )
    assert data.items[0].sound is False and data.items[0].origin == "user"
    data, log = pops.apply_ops(data, {"remove": ["pop_0001"]}, "user")
    assert data.items == [] and log == ["tolto pop_0001"]


def test_invalid_ops_are_rejected():
    with pytest.raises(pops.PopupError, match="word_id"):
        pops.apply_ops(
            pops.PopupsFile(), {"add": [{"word_id": "w9", "kind": "text", "title": "x"}]}, "ai"
        )
    with pytest.raises(pops.PopupError, match="emoji"):
        pops.apply_ops(pops.PopupsFile(), {"add": [{"at_ms": 10, "kind": "emoji"}]}, "ai")
    with pytest.raises(pops.PopupError, match="non trovato"):
        pops.apply_ops(pops.PopupsFile(), {"update": [{"id": "pop_0009", "title": "x"}]}, "ai")


def test_prompts_carry_style_logic_and_words():
    words = [("w000001", "Ciao", 1200)]
    s = pops.suggest_prompt(
        style_id="viral", style_name="Viral", words=words, data=pops.PopupsFile()
    )
    assert "VIRAL" in s and "w000001 @ 1.20s  Ciao" in s and '"word_id"' in s
    c = pops.chat_prompt(
        style_id="premium", style_name="Premium", words=words, data=pops.PopupsFile(),
        request="metti una card", time_ms=1500,
    )  # fmt: skip
    assert "PREMIUM" in c and "metti una card" in c and "1.50s" in c


def test_render_uses_popups_and_skips_rejected_and_ungenerated(tmp_path):
    from autocut.render.preview import Piece

    data = pops.PopupsFile(
        seeded=True,
        items=[
            pops.Popup(id="pop_0001", at_ms=1100, kind="emoji", emoji="💸", title="SOLDI"),
            pops.Popup(id="pop_0002", at_ms=1200, kind="text", title="no", status="rejected"),
            pops.Popup(id="pop_0003", at_ms=1300, kind="image", image_prompt="beach"),
            pops.Popup(id="pop_0004", at_ms=9000, kind="text", title="tagliato"),
        ],
    )
    pops.save(tmp_path, data)
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    cards = _cards(tmp_path, [Piece(1000, 2000, 0)], [], look)
    assert [(c["id"], c["emoji"], c["from_ms"], c["to_ms"]) for c in cards] == [
        ("pop_0001", "💸", 100, 2300)]  # fmt: skip


# --- API dell'editor --------------------------------------------------------------------


def _with_ask(c, answer):
    calls = []

    def ask_json(prompt):
        calls.append(prompt)
        return answer

    c.fake_agent.ask_json = ask_json
    return calls


def test_suggest_and_chat_apply_claude_ops(client):  # noqa: F811
    c, pdir = client
    c.post("/api/style", json={"id": "viral"})
    calls = _with_ask(c, {
        "add": [{"word_id": "w000003", "kind": "emoji", "emoji": "👋", "title": "CIAO",
                 "reason": "saluto"}],
        "message": "Ho aggiunto un saluto.",
    })  # fmt: skip
    p = c.post("/api/popups/suggest").json()
    assert "VIRAL" in calls[0] and p["popup_message"] == "Ho aggiunto un saluto."
    assert [(x["id"], x["at_ms"], x["origin"]) for x in p["popups"]] == [("pop_0001", 3100, "ai")]

    calls = _with_ask(c, {"update": [{"id": "pop_0001", "emoji": "🌴"}], "message": "fatto"})
    p = c.post("/api/popups/chat", json={"prompt": "metti una palma", "time_ms": 3200}).json()
    assert "metti una palma" in calls[0] and p["popups"][0]["emoji"] == "🌴"
    saved = json.loads((pdir / "popups.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["emoji"] == "🌴"

    _with_ask(c, {"add": [{"word_id": "nessuna", "kind": "text", "title": "x"}]})
    assert c.post("/api/popups/suggest").status_code == 502


def test_item_actions_and_generation(client):  # noqa: F811
    c, pdir = client
    _with_ask(
        c, {"add": [{"at_ms": 3100, "kind": "image", "image_prompt": "a beach", "reason": "r"}]}
    )
    c.post("/api/popups/suggest")
    p = c.post("/api/popups/item", json={"id": "pop_0001", "action": "approve"}).json()
    assert p["popups"][0]["status"] == "approved" and p["popups"][0]["origin"] == "user"
    p = c.post(
        "/api/popups/item", json={"id": "pop_0001", "action": "update", "fields": {"sound": False}}
    ).json()
    assert p["popups"][0]["sound"] is False

    # genera con Higgsfield: crea la richiesta, e quando è pronta l'immagine si collega
    p = c.post("/api/popups/generate", json={"id": "pop_0001"}).json()
    item = p["popups"][0]
    assert item["ai_request"] == "ai_0001" and c.fake_agent.calls[-1][2] == "image"
    assert item["image_url"] == "/media/ai/results/ai_0001-1.mp4"  # il finto scarica un .mp4

    assert (
        c.post("/api/popups/item", json={"id": "pop_0001", "action": "delete"}).json()["popups"]
        == []
    )
    assert (
        c.post("/api/popups/item", json={"id": "pop_0001", "action": "approve"}).status_code == 404
    )


def test_popups_show_one_at_a_time(tmp_path):
    from autocut.render.preview import Piece

    pops.save(
        tmp_path,
        pops.PopupsFile(
            seeded=True,
            items=[
                pops.Popup(id="pop_0001", at_ms=1000, kind="emoji", emoji="🌴"),
                pops.Popup(id="pop_0002", at_ms=2000, kind="emoji", emoji="🍕"),
            ],
        ),
    )
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    cards = _cards(tmp_path, [Piece(0, 9000, 0)], [], look)
    assert [(c["from_ms"], c["to_ms"]) for c in cards] == [(1000, 2000), (2000, 4200)]


# --- parsimonia, stili, proposta automatica --------------------------------------------


def test_limits_scale_with_duration_and_style():
    assert pops.limits("viral", 70_000) == (7, 4500)
    assert pops.limits("premium", 70_000) == (4, 8000)
    assert pops.limits(None, 5_000) == (1, 8000)  # almeno uno


def test_automatic_proposals_are_capped_and_spaced():
    adds = [{"at_ms": t, "kind": "emoji", "emoji": "✨"} for t in (1000, 2000, 7000, 13000, 19000)]
    data, log = pops.apply_ops(
        pops.PopupsFile(), {"add": adds}, "ai", style="viral", min_gap_ms=4500, max_count=2
    )
    assert [(x.at_ms, x.style) for x in data.items] == [(1000, "viral"), (7000, "viral")]
    assert sum(x.startswith("saltato") for x in log) == 3


def test_placement_rules():
    with pytest.raises(ValueError, match="coppia"):
        pops.Popup(id="pop_0001", at_ms=0, kind="text", title="x", placement="pair")
    p = pops.Popup(
        id="pop_0001", at_ms=0, kind="emoji", emoji="🇨🇳🇺🇸", placement="pair", style="viral"
    )
    assert p.visible_for("viral") and not p.visible_for("premium")


def test_render_passes_placement_and_hides_other_styles(tmp_path):
    from autocut.render.preview import Piece

    pops.save(
        tmp_path,
        pops.PopupsFile(
            seeded=True,
            items=[
                pops.Popup(id="pop_0001", at_ms=1000, kind="text", title="60s",
                           placement="behind", size="large", style="premium"),
                pops.Popup(id="pop_0002", at_ms=4000, kind="emoji", emoji="💪", style="viral"),
            ],
        ),
    )  # fmt: skip
    look = resolve_look(load_style(STYLES_DIR / "premium" / "style.json"), None, portrait=True)
    cards = _cards(tmp_path, [Piece(0, 9000, 0)], [], look)
    assert [(c["id"], c["placement"], c["size"], c["kind"]) for c in cards] == [
        ("pop_0001", "behind", "large", "text")]  # fmt: skip


def test_style_choice_triggers_one_automatic_proposal(tmp_path, monkeypatch):
    import autocut.editor.server as server

    class NowThread:  # il lavoro in background parte subito, così il test è deterministico
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server.threading, "Thread", NowThread)
    from .test_editor_server import make_client

    c, pdir = make_client(tmp_path, auto_popups=True)
    add = {
        "word_id": "w000003",
        "kind": "emoji",
        "emoji": "👋",
        "placement": "above",
        "size": "small",
    }
    calls = _with_ask(c, {"add": [add], "message": "uno solo"})
    p = c.post("/api/style", json={"id": "viral"}).json()
    assert len(calls) == 1 and "AL MASSIMO 1 pop-up" in calls[0]
    assert p["popup_job"]["status"] == "done" and p["popups"][0]["placement"] == "above"
    assert json.loads((pdir / "popups.json").read_text(encoding="utf-8"))["suggested"] == ["viral"]

    c.get("/api/project")  # già analizzato per questo stile: non richiama Claude
    assert len(calls) == 1
    p = c.post("/api/style", json={"id": "premium"}).json()
    # nuova proposta per il premium; quella viral non compare qui
    assert len(calls) == 2 and [x["style"] for x in p["popups"]] == ["premium"]


# --- pannello Sticker ------------------------------------------------------------------


def test_free_stickers_need_a_position_and_know_their_layer():
    with pytest.raises(ValueError, match="posizione"):
        pops.Popup(id="pop_0001", at_ms=0, kind="emoji", emoji="🔥", placement="free")
    p = pops.Popup(id="pop_0001", at_ms=0, kind="emoji", emoji="🔥", placement="free",
                   x_pct=70, y_pct=60, scale=1.6, rotation=20, layer="over_text")  # fmt: skip
    assert not p.behind_person
    assert pops.Popup(
        id="pop_0002", at_ms=0, kind="text", title="60s", placement="behind"
    ).behind_person
    with pytest.raises(ValueError):
        pops.Popup(id="pop_0003", at_ms=0, kind="emoji", emoji="🔥", placement="free",
                   x_pct=50, y_pct=50, scale=9)  # fmt: skip
    for lib in pops.STICKERS.values():
        assert len(lib["emoji"]) >= 8 and len(lib["text"]) >= 6


def test_render_keeps_free_stickers_together_with_their_layer(tmp_path):
    from autocut.render.preview import Piece

    pops.save(
        tmp_path,
        pops.PopupsFile(
            seeded=True,
            items=[
                pops.Popup(id="pop_0001", at_ms=1000, kind="emoji", emoji="🌴"),
                pops.Popup(id="pop_0002", at_ms=1500, kind="emoji", emoji="🔥", placement="free",
                           x_pct=70, y_pct=60, rotation=20, scale=1.6, layer="over_text"),
                pops.Popup(id="pop_0003", at_ms=1800, kind="text", title="WOW", placement="free",
                           x_pct=30, y_pct=20, layer="person"),
            ],
        ),
    )  # fmt: skip
    look = resolve_look(load_style(STYLES_DIR / "viral" / "style.json"), None, portrait=True)
    cards = {c["id"]: c for c in _cards(tmp_path, [Piece(0, 9000, 0)], [], look)}
    # gli sticker messi a mano non tagliano gli altri: restano tutti a schermo
    assert cards["pop_0001"]["to_ms"] == 1000 + 2200
    assert cards["pop_0002"]["layer"] == "over_text" and cards["pop_0002"]["rotation"] == 20
    assert (cards["pop_0002"]["x_pct"], cards["pop_0002"]["scale"]) == (70, 1.6)
    assert cards["pop_0003"]["layer"] == "person"


def test_sticker_api_adds_moves_and_layers(client):  # noqa: F811
    c, pdir = client
    c.post("/api/style", json={"id": "viral"})
    p = c.get("/api/project").json()
    assert "🔥" in p["stickers"]["emoji"] and p["stickers"]["images"] == []
    p = c.post("/api/popups/add", json={"kind": "emoji", "emoji": "🔥", "at_ms": 1200}).json()
    new = next(x for x in p["popups"] if x["id"] == p["added"])
    assert (new["placement"], new["status"], new["style"], new["x_pct"]) == (
        "free",
        "approved",
        "viral",
        50,
    )
    move = {"x_pct": 80, "y_pct": 20, "rotation": -15, "scale": 2, "layer": "over_text"}
    body = {"id": new["id"], "action": "update", "fields": move}
    p = c.post("/api/popups/item", json=body).json()
    moved = next(x for x in p["popups"] if x["id"] == new["id"])
    assert (moved["x_pct"], moved["rotation"], moved["layer"]) == (80, -15, "over_text")
    assert c.post("/api/popups/add", json={"kind": "image", "image": "ai/results/nope.png",
                                           "at_ms": 0}).status_code == 404  # fmt: skip
    c.post("/api/style", json={"id": "premium"})
    p = c.get("/api/project").json()
    assert all(x["id"] != new["id"] for x in p["popups"])  # lo sticker vale solo per il viral
    assert "📈" in p["stickers"]["emoji"]


def test_emoji_images_split_sequences(tmp_path):
    from autocut import emoji as emo

    root = tmp_path / "emoji"
    (root / "apple").mkdir(parents=True)
    items = [
        {"e": "🔥", "img": "1f525.png"},
        {"e": "🇮🇹", "img": "1f1ee-1f1f9.png"},
        {"e": "❤️", "img": "2764-fe0f.png"},
        {"e": "🤷‍♂️", "img": "1f937-200d-2642-fe0f.png"},
    ]
    (root / "index.json").write_text(
        json.dumps({"categories": [{"name": "Smileys & Emotion", "items": items}]}),
        encoding="utf-8",
    )
    assert emo.images_for("🇮🇹🔥", root) == ["1f1ee-1f1f9.png", "1f525.png"]
    assert emo.images_for("❤", root) == ["2764-fe0f.png"]  # con o senza variation selector
    assert emo.images_for("🤷‍♂️", root) == ["1f937-200d-2642-fe0f.png"]
    assert emo.images_for("🔥 ciao", root) is None  # testo: resta al font
    assert emo.NAME_RE.match("1f1ee-1f1f9.png") and not emo.NAME_RE.match("../x.png")


def test_emoji_api_without_library(client, monkeypatch, tmp_path):  # noqa: F811
    from autocut import emoji as emo

    c, _ = client
    monkeypatch.setattr(emo, "EMOJI_DIR", tmp_path / "nessuna")
    assert c.get("/api/emoji").json() == {"available": False, "categories": []}
    assert c.get("/media/emoji/1f525.png").status_code == 404
    assert c.get("/media/emoji/..%2Fsecret.png").status_code == 404
