"""API dell'editor con un progetto finto (nessun video vero, nessun ffmpeg)."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autocut.editor.ai_jobs import AiQueue
from autocut.editor.media import EditorMedia
from autocut.editor.server import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "timeline_example.json"
GAP = "gap:w000002-w000003"


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def make_client(tmp_path, **app_kwargs):
    pdir = tmp_path / "episodio-12"
    pdir.mkdir()
    shutil.copy(FIXTURE, pdir / "timeline.json")
    work = pdir / "work"
    thumbs = work / "thumbs"
    thumbs.mkdir(parents=True)
    (thumbs / "00001.jpg").write_bytes(b"\xff\xd8jpg")
    proxy = work / "proxy.mp4"
    proxy.write_bytes(b"\x00" * 4096)
    wave = work / "wave.json"
    wave.write_text(json.dumps({"bucket_ms": 10, "peaks": [0, 50, 100]}))
    media = EditorMedia(
        proxy=proxy,
        offset_ms=0,
        duration_ms=5200,
        thumbs_dir=thumbs,
        thumb_interval_ms=1000,
        thumb_count=1,
        waveform=wave,
    )

    agent = FakeAgent()
    queue = AiQueue(
        pdir,
        media,
        project="episodio-12",
        portrait=False,
        words=lambda: [],
        agent=agent,
        executor=SyncExecutor(),
        downloader=fake_download,
        frame_grabber=fake_grab,
    )
    test_client = TestClient(create_app(pdir, media, queue=queue, **app_kwargs))
    test_client.fake_agent = agent
    return test_client, pdir


def fake_grab(proxy_path, seconds, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\xff\xd8frame")
    return dest


def fake_download(url, dest_stem):
    dest = dest_stem.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"video")
    return dest


class SyncExecutor:
    def submit(self, fn, *args):
        fn(*args)


class FakeAgent:
    server = "higgsfield"

    def __init__(self):
        self.calls = []
        self.json_reply = {}

    def ask_json(self, prompt):
        self.calls.append(("ask_json", prompt))
        return self.json_reply

    def status(self, refresh=False):
        return {"claude": True, "higgsfield": "connected", "server": self.server}

    def suggest(self, ctx):
        self.calls.append(("suggest", ctx))
        return [{"kind": "video", "title": "Spiaggia", "prompt": "p", "why": "w", "duration_s": 3}]

    def generate(self, ctx, kind, request):
        self.calls.append(("generate", ctx, kind, request))
        return {"status": "done", "urls": ["https://cdn.example/x.mp4"], "model": "m", "note": "ok"}


def test_project_payload(client):
    c, _ = client
    p = c.get("/api/project").json()
    assert p["project"] == "episodio-12"
    assert [d["id"] for d in p["decisions"]] == ["gap:^-w000001", GAP, "gap:w000005-$"]
    assert p["decisions"][1]["label"] == "Pausa"
    assert p["decisions"][0]["label"] == "Silenzio iniziale"
    assert p["summary"]["raw_ms"] == 5200
    assert p["groups"][0]["chosen"] == "take:w000003"
    assert p["summary"]["can_undo"] is False


def test_flip_writes_overrides_and_undo_restores(client):
    c, pdir = client
    p = c.post("/api/decision", json={"id": GAP, "action": "flip"}).json()
    d = next(x for x in p["decisions"] if x["id"] == GAP)
    assert (d["effective"], d["overridden"], d["reviewed"]) == ("keep", True, True)
    saved = json.loads((pdir / "overrides.json").read_text(encoding="utf-8"))
    assert saved["overrides"][GAP]["value"] == {"state": "keep"}
    assert json.loads((pdir / "timeline.json").read_text(encoding="utf-8")) == json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )  # la timeline non viene mai riscritta

    p = c.post("/api/undo", json={}).json()
    d = next(x for x in p["decisions"] if x["id"] == GAP)
    assert (d["effective"], d["overridden"], d["reviewed"]) == ("remove", False, False)
    assert p["summary"]["history"] == 2


def test_accept_and_bulk_review(client):
    c, _ = client
    p = c.post("/api/decision", json={"id": GAP, "action": "accept"}).json()
    assert next(x for x in p["decisions"] if x["id"] == GAP)["reviewed"] is True
    ids = [d["id"] for d in p["decisions"]]
    p = c.post("/api/reviewed", json={"ids": ids, "value": True}).json()
    assert all(d["reviewed"] for d in p["decisions"])
    assert c.post("/api/reviewed", json={"ids": ["boh"]}).status_code == 404


def test_choose_take(client):
    c, _ = client
    p = c.post("/api/group", json={"id": "rg:w000001", "take_id": "take:w000001"}).json()
    assert p["groups"][0]["chosen"] == "take:w000001"
    assert p["groups"][0]["overridden"] is True
    bad = c.post("/api/group", json={"id": "rg:w000001", "take_id": "take:nope"})
    assert bad.status_code == 400


def test_errors(client):
    c, _ = client
    assert c.post("/api/decision", json={"id": "gap:nope", "action": "flip"}).status_code == 404
    assert c.post("/api/decision", json={"id": GAP, "action": "boh"}).status_code == 400
    assert c.post("/api/undo", json={}).status_code == 400


def test_ai_request_runs_immediately_and_downloads_the_result(client):
    c, pdir = client
    p = c.post("/api/ai-requests", json={"time_ms": 3200, "prompt": " spiaggia ", "kind": "video"})
    req = p.json()["ai_requests"][0]
    assert (req["id"], req["prompt"], req["status"], req["time_ms"]) == (
        "ai_0001",
        "spiaggia",
        "done",
        3200,
    )
    assert req["result"]["local"] == ["/media/ai/results/ai_0001-1.mp4"]
    assert c.get(req["frame"]).status_code == 200
    assert c.get(req["result"]["local"][0]).content == b"video"
    assert c.post("/api/ai-requests", json={"time_ms": 0, "prompt": "  "}).status_code == 400
    assert (
        c.post("/api/ai-requests", json={"time_ms": 0, "prompt": "x", "kind": "x"}).status_code
        == 400
    )
    assert c.get("/media/ai/..%2Ftimeline.json").status_code == 404


def test_ai_request_can_wait_in_queue_and_run_later(client):
    c, _ = client
    req = c.post(
        "/api/ai-requests", json={"time_ms": 0, "prompt": "titolo", "kind": "graphic", "run": False}
    ).json()["ai_requests"][0]
    assert req["status"] == "queued"
    done = c.post("/api/ai-requests/run", json={"id": req["id"]}).json()["ai_requests"][0]
    assert done["status"] == "done"
    assert c.post("/api/ai-requests/run", json={"id": "ai_9999"}).status_code == 404


def test_ai_suggest_and_status(client):
    c, _ = client
    res = c.post("/api/ai-suggest", json={"time_ms": 1300}).json()
    assert res["suggestions"][0]["title"] == "Spiaggia"
    assert res["frame"] == "/media/ai/suggest-1300.jpg"
    assert c.get("/api/ai-status").json()["higgsfield"] == "connected"


def test_brand_selection_is_saved_and_keeps_reviews(client):
    c, pdir = client
    p = c.get("/api/project").json()
    assert p["brand"] is None
    assert {b["id"] for b in p["brands"]} >= {"federico", "editoriale-chiaro"}

    c.post("/api/decision", json={"id": GAP, "action": "accept"})
    p = c.post("/api/brand", json={"id": "federico"}).json()
    assert p["brand"]["id"] == "federico"
    assert p["brand"]["google_fonts_url"].startswith("https://fonts.googleapis.com/")
    assert next(d for d in p["decisions"] if d["id"] == GAP)["reviewed"] is True

    c.post("/api/decision", json={"id": GAP, "action": "reset"})  # riscrive lo stato
    state = json.loads((pdir / "editor_state.json").read_text(encoding="utf-8"))
    assert state["brand"] == "federico" and state["reviewed"] == []

    assert c.post("/api/brand", json={"id": "nessuno"}).status_code == 404
    assert c.post("/api/brand", json={"id": None}).json()["brand"] is None


def test_brand_is_passed_to_claude(client):
    c, _ = client
    c.post("/api/ai-suggest", json={"time_ms": 0})
    assert c.fake_agent.calls[-1][1].brand == ""  # nessun brand scelto

    c.post("/api/brand", json={"id": "federico"})
    c.post("/api/ai-suggest", json={"time_ms": 0})
    assert "Federico Batildi" in c.fake_agent.calls[-1][1].brand
    c.post("/api/ai-requests", json={"time_ms": 0, "prompt": "titolo", "kind": "graphic"})
    kind, ctx = c.fake_agent.calls[-1][0], c.fake_agent.calls[-1][1]
    assert kind == "generate" and "#2f6bff" in ctx.brand


def test_style_is_combined_with_brand_and_given_to_claude(client):
    c, pdir = client
    p = c.get("/api/project").json()
    assert p["style"] is None and {s["id"] for s in p["styles"]} == {"premium", "viral"}

    c.post("/api/brand", json={"id": "federico"})
    p = c.post("/api/style", json={"id": "viral"}).json()
    assert p["style"]["style"] == "viral" and p["style"]["brand"] == "federico"
    assert p["style"]["captions"]["emphasis"]["color"] == "#F6B25A"  # highlight del brand
    state = json.loads((pdir / "editor_state.json").read_text(encoding="utf-8"))
    assert state["style"] == "viral" and state["brand"] == "federico"

    c.post("/api/ai-suggest", json={"time_ms": 0})
    ctx = c.fake_agent.calls[-1][1].brand
    assert "Federico Batildi" in ctx and "Viral provinciale" in ctx and "Sticker" in ctx

    assert c.post("/api/style", json={"id": "boh"}).status_code == 404
    assert c.post("/api/style", json={"id": None}).json()["style"] is None


def test_media_and_static(client):
    c, _ = client
    assert c.get("/").status_code == 200
    assert "autocut" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    r = c.get("/media/video", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100  # serve lo scrubbing del browser
    assert c.get("/media/thumbs/1.jpg").status_code == 200
    assert c.get("/media/thumbs/9.jpg").status_code == 404
