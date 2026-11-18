"""«Chiedi a Claude»: chat dell'editor collegata a Claude Code (Claude finto, niente costi)."""

import json
import shutil
import subprocess

import pytest

from autocut.editor import assistant as asst

from .test_editor_server import make_client

GIT = shutil.which("git")


def _emoji_runner(calls):
    """Claude finto in modalità Edita: aggiunge l'emoji del pianto sotto la frase."""

    def run(prompt, *, cwd, tools, timeout, resume=None, on_step=lambda s: None):
        calls.append({"prompt": prompt, "cwd": cwd, "tools": tools, "resume": resume})
        ctx = json.loads((cwd / "context.json").read_text(encoding="utf-8"))
        on_step("Leggo GUIDA.md")
        assert (cwd / "GUIDA.md").is_file()
        p = cwd / "popups.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"items": []}
        at = ctx["selection"]["start_ms"]
        data["items"].append({"id": "pop_9001", "at_ms": at, "duration_ms": 2000, "kind": "emoji",
                              "emoji": "😭", "placement": "center", "status": "approved",
                              "origin": "ai", "style": ctx["style"]})  # fmt: skip
        on_step("Modifico popups.json")
        p.write_text(json.dumps(data), encoding="utf-8")
        return {"text": '{"summary": "Emoji del pianto sotto la frase.", "missing": '
                '"filtro bianco e nero per un solo tratto"}', "session_id": "sess-1",
                "is_error": False}  # fmt: skip

    return run


def test_edit_mode_applies_validated_changes_with_one_undo(tmp_path):
    calls = []
    c, pdir = make_client(tmp_path, claude_runner=_emoji_runner(calls), assistant_threaded=False)
    body = {"mode": "edit", "prompt": "bianco e nero e sotto la frase l'emoji del pianto",
            "selection": {"start_ms": 1000, "end_ms": 2500,
                          "captions": [{"id": "w1", "text": "no", "start_ms": 1000}]}}  # fmt: skip
    out = c.post("/api/assistant", json=body).json()
    m = out["messages"][-1]
    assert m["status"] == "done", m.get("error")
    assert m["changed"] == ["popups.json"] and "pianto" in m["summary"]
    assert m["missing"].startswith("filtro")  # quello che manca all'editor lo dice
    assert [s["text"] for s in m["steps"]] == ["Leggo GUIDA.md", "Modifico popups.json"]
    items = json.loads((pdir / "popups.json").read_text(encoding="utf-8"))["items"]
    assert any(x["id"] == "pop_9001" and x["emoji"] == "😭" for x in items)
    ctx = json.loads((pdir / asst.STAGING / "context.json").read_text(encoding="utf-8"))
    assert ctx["captions"][0]["id"] == "w1" and "anims" in ctx["catalog"]
    assert "Edit" not in calls[0]["tools"]  # le modifiche solo nella cartella (acceptEdits)
    # un solo Annulla toglie tutto quello che ha fatto Claude
    c.post("/api/history/undo")
    after = (
        (pdir / "popups.json").read_text(encoding="utf-8")
        if (pdir / "popups.json").exists()
        else ""
    )
    assert "pop_9001" not in after
    # il messaggio dopo continua la stessa conversazione
    c.post("/api/assistant", json={**body, "prompt": "più grande"})
    assert calls[-1]["resume"] == "sess-1"


def test_edit_mode_rejects_an_invalid_file_and_changes_nothing(tmp_path):
    def bad(prompt, *, cwd, tools, timeout, resume=None, on_step=lambda s: None):
        (cwd / "effects.json").write_text(
            '{"styles": {"viral": {"captions": 7}}}', encoding="utf-8"
        )
        return {"text": '{"summary": "fatto"}', "session_id": None, "is_error": False}

    c, pdir = make_client(tmp_path, claude_runner=bad, assistant_threaded=False)
    m = c.post("/api/assistant", json={"mode": "edit", "prompt": "x"}).json()["messages"][-1]
    assert m["status"] == "error" and "effects.json non valido" in m["error"]
    assert not (pdir / "effects.json").exists()


def test_api_guards(tmp_path):
    c, pdir = make_client(tmp_path, claude_runner=_emoji_runner([]))
    assert c.post("/api/assistant", json={"mode": "boh", "prompt": "x"}).status_code == 400
    assert c.post("/api/assistant/restart").status_code == 409  # senza supervisore
    data = {"messages": [{"id": "m1", "mode": "edit", "prompt": "x", "status": "running",
                          "t0": 0}], "sessions": {}}  # fmt: skip
    (pdir / asst.CHAT_FILE).write_text(json.dumps(data), encoding="utf-8")
    assert c.post("/api/assistant", json={"mode": "edit", "prompt": "y"}).status_code == 409
    assert c.post("/api/assistant/clear").status_code == 409
    assert c.get("/api/assistant").json()["running"] is True


def test_describe_tool_is_readable():
    assert asst.describe_tool("Edit", {"file_path": "C:/x/app.js"}) == "Modifico app.js"
    assert asst.describe_tool("Bash", {"command": "uv run --no-sync pytest -q"}) == "Eseguo i test"
    assert asst.describe_tool("Grep", {"pattern": "vfx"}) == "Cerco «vfx»"


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.skipif(GIT is None, reason="serve git")
def test_dev_mode_tracks_code_changes_restarts_and_reverts(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "autocut").mkdir(parents=True)
    (repo / "src" / "autocut" / "x.py").write_text("A = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    (repo / "src" / "autocut" / "x.py").write_text("A = 2\n", encoding="utf-8")  # già modificato
    (repo / "src" / "autocut" / "mio.py").write_text("C = 1\n", encoding="utf-8")  # non in git

    def dev(prompt, *, cwd, tools, timeout, resume=None, on_step=lambda s: None):
        assert cwd == repo and "Bash(git commit:*)" not in tools
        on_step("Modifico x.py")
        (repo / "src" / "autocut" / "x.py").write_text("A = 3\n", encoding="utf-8")
        (repo / "src" / "autocut" / "nuovo.py").write_text("B = 1\n", encoding="utf-8")
        (repo / "src" / "autocut" / "mio.py").write_text("C = 2\n", encoding="utf-8")
        return {"text": '{"summary": "Nuova scheda.", "how_to_use": "scheda X", "tests": "ok"}',
                "session_id": "dev-1", "is_error": False}  # fmt: skip

    pdir = tmp_path / "proj"
    pdir.mkdir()
    a = asst.Assistant(pdir, repo, context=lambda s: {}, apply_edit=lambda c: None, runner=dev)
    job = a.start("dev", "aggiungi una scheda", None)
    m = a.run(job["id"])
    assert m["status"] == "done" and m["restart"] is True and m["how_to_use"] == "scheda X"
    assert m["files"] == {
        "changed": ["src/autocut/mio.py", "src/autocut/x.py"],
        "added": ["src/autocut/nuovo.py"],
    }
    a.revert(job["id"])
    # torna com'era PRIMA del lavoro (anche la modifica non salvata A = 2 e il file non ancora
    # in git), il file nuovo sparisce, niente finisce in stage
    assert (repo / "src" / "autocut" / "x.py").read_text(encoding="utf-8") == "A = 2\n"
    assert (repo / "src" / "autocut" / "mio.py").read_text(encoding="utf-8") == "C = 1\n"
    assert not (repo / "src" / "autocut" / "nuovo.py").exists()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert staged == ""
    with pytest.raises(asst.AssistantError):
        a.revert(job["id"])
    assert "snapshot" not in a.payload()["messages"][0]  # la fotografia non va al browser
