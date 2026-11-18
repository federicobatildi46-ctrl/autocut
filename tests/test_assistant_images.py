"""«Chiedi a Claude»: screenshot incollati nella chat (Claude finto, niente costi)."""

import json

from autocut.editor import assistant as asst

from .test_editor_server import make_client

PNG = "data:image/png;base64,iVBORw0KGgo="  # basta l'intestazione: il Claude finto non decodifica


def _ok(text="visto"):
    return {"text": json.dumps({"summary": text}), "session_id": "s", "is_error": False}


def test_pasted_screenshots_reach_claude_and_are_served(tmp_path):
    seen = {}

    def run(prompt, *, cwd, tools, timeout, resume=None, on_step=lambda s: None):
        seen["prompt"] = prompt
        seen["files"] = sorted(p.name for p in cwd.glob("allegato_*"))
        return _ok()

    c, _ = make_client(tmp_path, claude_runner=run, assistant_threaded=False)
    out = c.post("/api/assistant", json={"mode": "edit", "prompt": "", "images": [PNG]}).json()
    m = out["messages"][-1]
    assert m["status"] == "done" and len(m["images"]) == 1  # il testo è facoltativo
    assert seen["files"] == ["allegato_1.png"] and "allegato_1.png" in seen["prompt"]
    r = c.get(f"/api/assistant/image/{m['images'][0]}")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert c.get("/api/assistant/image/..%2Fsecret.png").status_code == 404
    assert c.get("/api/assistant/image/msg_1_1_1.png").status_code == 404


def test_screenshots_are_validated(tmp_path):
    c, _ = make_client(tmp_path, claude_runner=lambda *a, **k: _ok(), assistant_threaded=False)

    def post(**kw):
        return c.post("/api/assistant", json={"mode": "edit", "prompt": "x", **kw})

    assert post(images=["data:text/html;base64,AAAA"]).status_code == 400
    assert post(images=[PNG] * 5).status_code == 422  # massimo 4
    big = "data:image/png;base64," + "A" * (asst.MAX_IMAGE_BYTES * 4 // 3 + 100)
    assert post(images=[big]).status_code == 400
    assert c.post("/api/assistant", json={"mode": "edit", "prompt": ""}).status_code == 400


def test_dev_mode_gets_the_screenshot_path_and_read_access(tmp_path):
    seen = {}

    def run(prompt, *, cwd, tools, timeout, resume=None, on_step=lambda s: None, add_dirs=None):
        seen.update(prompt=prompt, add_dirs=add_dirs)
        return _ok("ok")

    c, pdir = make_client(
        tmp_path, claude_runner=run, assistant_threaded=False, assistant_git=False
    )
    c.post("/api/assistant", json={"mode": "dev", "prompt": "guarda", "images": [PNG]})
    assert seen["add_dirs"] == [pdir / asst.ATTACH]
    assert str(pdir / asst.ATTACH) in seen["prompt"]


def test_screenshot_tool_is_shipped_with_the_editor(tmp_path):
    """Lo strumento screenshot è tutto lato browser: si controlla che la pagina lo serva."""
    c, _ = make_client(tmp_path, claude_runner=lambda *a, **k: _ok(), assistant_threaded=False)
    js = c.get("/static/app.js").text
    css = c.get("/static/styles.css").text
    assert "getDisplayMedia" in js and 'data-ask="shot"' in js and "shotSend" in js
    assert ".shot-stage" in css and "body.shooting" in css
