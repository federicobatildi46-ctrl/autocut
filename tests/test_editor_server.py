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
def client(tmp_path, monkeypatch):
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

    queue = AiQueue(
        pdir,
        media,
        project="episodio-12",
        portrait=False,
        words=lambda: [],
        agent=FakeAgent(),
        executor=SyncExecutor(),
        downloader=fake_download,
        frame_grabber=fake_grab,
    )
    return TestClient(create_app(pdir, media, queue=queue)), pdir


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


def test_media_and_static(client):
    c, _ = client
    assert c.get("/").status_code == 200
    assert "autocut" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    r = c.get("/media/video", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100  # serve lo scrubbing del browser
    assert c.get("/media/thumbs/1.jpg").status_code == 200
    assert c.get("/media/thumbs/9.jpg").status_code == 404
