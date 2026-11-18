"""Agente Claude + Higgsfield senza chiamare davvero Claude (subprocess finto)."""

import json
import subprocess
from pathlib import Path

import pytest

from autocut.editor import agent as agent_mod
from autocut.editor.agent import (
    AgentError,
    ClaudeAgent,
    FrameContext,
    budget_for,
    child_env,
    extract_json,
    generate_prompt,
    parse_account_status,
    suggest_prompt,
)
from autocut.editor.ai_jobs import AiQueue
from autocut.editor.media import EditorMedia
from autocut.models.timeline import Word

CTX = FrameContext(
    frame_path=Path("C:/p/work/ai/req-0001.jpg"),
    time_ms=62000,
    rel_ms=62000,
    portrait=True,
    transcript="voglio andarmene in Thailandia",
    project="test",
)


def test_extract_json_from_fenced_or_plain_text():
    assert extract_json('ecco:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('testo {"x": {"y": 2}} fine') == {"x": {"y": 2}}
    assert extract_json('{"a": 1} e poi {"b": 2}') == {"b": 2}  # l'ultimo vince
    with pytest.raises(AgentError):
        extract_json("niente json")


def test_parse_account_status():
    ok = parse_account_status(0, '{"credits": 268, "subscription_plan_type": "starter"}', "")
    assert ok == {"higgsfield": "connected", "credits": 268, "plan": "starter"}
    ws = parse_account_status(4, "", "Error: No workspace selected.\nHint: Run: hf workspace set")
    assert ws["higgsfield"] == "no_workspace"
    assert parse_account_status(1, "", "Error: not logged in")["higgsfield"] == "needs_auth"
    assert parse_account_status(1, "", "boom")["higgsfield"] == "error"


def test_prompts_carry_frame_format_context_and_budget():
    s = suggest_prompt(CTX)
    assert str(CTX.frame_path) in s and "9:16" in s and "Thailandia" in s
    assert '"suggestions"' in s
    g = generate_prompt(CTX, "image", "spiaggia al tramonto", 6)
    assert "spiaggia al tramonto" in g and "higgsfield-generate" in g
    assert "aspect_ratio 9:16" in g and f'--image-references "{CTX.frame_path}"' in g
    assert "supera 6 crediti" in g and "UN SOLO job" in g and "non comprare crediti" in g


def test_budget_and_env(monkeypatch):
    assert budget_for("image") == 6 and budget_for("video") == 40
    monkeypatch.setenv("AUTOCUT_AI_BUDGET_VIDEO", "15")
    assert budget_for("video") == 15
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=4096")
    assert child_env()["NODE_OPTIONS"] == "--max-old-space-size=4096 --use-system-ca"


def _fake_run(result_text, is_error=False, record=None):
    def run(cmd, **kw):
        if record is not None:
            record.append((cmd, kw))
        envelope = {"type": "result", "is_error": is_error, "result": result_text}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(envelope).encode(), b"")

    return run


def test_suggest_uses_only_read_and_stdin(monkeypatch):
    calls = []
    text = json.dumps({"suggestions": [{"kind": "boh", "title": "T", "prompt": "P", "why": "W"}]})
    monkeypatch.setattr(agent_mod.subprocess, "run", _fake_run(text, record=calls))
    monkeypatch.setattr(ClaudeAgent, "executable", lambda self: "claude")
    ideas = ClaudeAgent().suggest(CTX)
    assert ideas == [{"kind": "video", "title": "T", "prompt": "P", "why": "W", "duration_s": None}]
    cmd, kw = calls[0]
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    assert cmd[cmd.index("--allowedTools") + 1 :] == ["Read"]
    assert "Thailandia" in kw["input"].decode("utf-8")


def test_generate_allows_only_higgsfield_commands(monkeypatch, tmp_path):
    calls = []
    out = '{"status": "done", "urls": ["https://x/y.png"]}'
    monkeypatch.setattr(agent_mod.subprocess, "run", _fake_run(out, record=calls))
    monkeypatch.setattr(ClaudeAgent, "executable", lambda self: "claude")
    agent = ClaudeAgent(workdir=tmp_path)
    assert agent.generate(CTX, "image", "x")["urls"] == ["https://x/y.png"]
    cmd, kw = calls[0]
    assert cmd[cmd.index("--allowedTools") + 1 :] == [
        "Read",
        "Skill",
        "Bash(higgsfield:*)",
        "Bash(hf:*)",
    ]
    assert kw["cwd"] == tmp_path  # le skill del progetto stanno qui
    assert "--use-system-ca" in kw["env"]["NODE_OPTIONS"]


def test_claude_errors_are_reported(monkeypatch):
    monkeypatch.setattr(ClaudeAgent, "executable", lambda self: "claude")
    monkeypatch.setattr(agent_mod.subprocess, "run", _fake_run("rate limit", is_error=True))
    with pytest.raises(AgentError, match="errore"):
        ClaudeAgent().suggest(CTX)
    monkeypatch.setattr(ClaudeAgent, "executable", lambda self: None)
    with pytest.raises(AgentError, match="non trovato"):
        ClaudeAgent().suggest(CTX)


class FailingAgent:
    server = "higgsfield"

    def status(self, refresh=False):
        return {"claude": True, "higgsfield": "connected", "server": self.server}

    def generate(self, ctx, kind, request):
        raise AgentError("saldo insufficiente")


class SyncExecutor:
    def submit(self, fn, *args):
        fn(*args)


def _queue(tmp_path, agent, words=()):
    media = EditorMedia(
        proxy=tmp_path / "p.mp4",
        offset_ms=0,
        duration_ms=70000,
        thumbs_dir=tmp_path,
        thumb_interval_ms=1000,
        thumb_count=0,
        waveform=tmp_path / "w.json",
    )

    def grab(proxy, seconds, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpg")
        return dest

    return AiQueue(
        tmp_path,
        media,
        project="test",
        portrait=True,
        words=lambda: list(words),
        agent=agent,
        executor=SyncExecutor(),
        frame_grabber=grab,
    )


def test_agent_failure_marks_the_request(tmp_path):
    q = _queue(tmp_path, FailingAgent())
    q.add(1000, "spiaggia", "video")
    req = q.requests()[0]
    assert (req["status"], req["note"]) == ("error", "saldo insufficiente")


def test_context_uses_words_around_the_frame(tmp_path):
    words = [
        Word(id="w000001", text="lontano", start_ms=1000, end_ms=1200),
        Word(id="w000002", text="Thailandia", start_ms=60000, end_ms=60500),
    ]
    q = _queue(tmp_path, FailingAgent(), words)
    ctx = q._context(62000, tmp_path / "f.jpg")
    assert ctx.transcript == "Thailandia" and ctx.portrait


def test_running_requests_become_interrupted_on_restart(tmp_path):
    (tmp_path / "ai_requests.json").write_text(
        json.dumps(
            {"requests": [{"id": "ai_0001", "status": "running", "frame": "/media/ai/x.jpg"}]}
        )
    )
    q = _queue(tmp_path, FailingAgent())
    assert q.requests()[0]["status"] == "interrupted"
