"""Coda delle richieste "Potenzia": ai_requests.json + esecuzione in background con l'agente.

Stati di una richiesta: queued -> running -> done | error (| interrupted se l'editor è stato
chiuso a metà). I file generati vengono scaricati in projects/<nome>/work/ai/results/.
"""

from __future__ import annotations

import json
import mimetypes
import ssl
import threading
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import truststore

from ..models.timeline import Word
from .agent import AgentError, ClaudeAgent, FrameContext
from .media import EditorMedia, grab_frame

AI_FILE = "ai_requests.json"
CONTEXT_MS = 8000
KINDS = ("video", "image", "graphic")
EXT_BY_TYPE = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

Downloader = Callable[[str, Path], Path]


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def download(url: str, dest_stem: Path) -> Path:
    """Scarica un risultato di Higgsfield (certificati di sistema). Estensione dal tipo."""
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(verify=ctx, timeout=300, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";")[0].strip()
        ext = (
            EXT_BY_TYPE.get(ctype)
            or Path(urlparse(url).path).suffix
            or (mimetypes.guess_extension(ctype) or ".bin")
        )
        dest = dest_stem.with_suffix(ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest


class AiQueue:
    def __init__(
        self,
        project_dir: Path,
        media: EditorMedia,
        *,
        project: str,
        portrait: bool,
        words: Callable[[], list[Word]],
        agent: ClaudeAgent | None = None,
        executor: Executor | None = None,
        downloader: Downloader = download,
        frame_grabber: Callable[[Path, float, Path], Path] = grab_frame,
    ):
        self.path = project_dir / AI_FILE
        self.ai_dir = project_dir / "work" / "ai"
        self.results_dir = self.ai_dir / "results"
        self.media = media
        self.project = project
        self.portrait = portrait
        self.words = words
        self.agent = agent or ClaudeAgent()
        self.executor = executor or ThreadPoolExecutor(max_workers=2)
        self.downloader = downloader
        self.grab = frame_grabber
        self.brand: Callable[[], str] = lambda: ""  # descrizione del brand attivo per Claude
        self.lock = threading.Lock()
        self._mark_interrupted()

    # --- file -------------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"requests": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".partial")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _update(self, req_id: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            for req in data["requests"]:
                if req["id"] == req_id:
                    req.update(fields, updated_at=_now())
                    self._save(data)
                    return req
        raise KeyError(req_id)

    def _mark_interrupted(self) -> None:
        with self.lock:
            data = self._load()
            changed = False
            for req in data["requests"]:
                if req.get("status") == "running":
                    req.update(
                        status="interrupted", note="l'editor è stato chiuso durante il lavoro"
                    )
                    changed = True
            if changed:
                self._save(data)

    def requests(self) -> list[dict[str, Any]]:
        with self.lock:
            return self._load()["requests"]

    # --- contesto -----------------------------------------------------------------------

    def _context(self, time_ms: int, frame: Path) -> FrameContext:
        near = [
            w.text
            for w in self.words()
            if w.end_ms >= time_ms - CONTEXT_MS and w.start_ms <= time_ms + CONTEXT_MS
        ]
        return FrameContext(
            frame_path=frame.resolve(),
            time_ms=time_ms,
            rel_ms=time_ms - self.media.offset_ms,
            portrait=self.portrait,
            transcript=" ".join(near),
            brand=self.brand(),
            project=self.project,
        )

    def _frame(self, time_ms: int, name: str) -> Path:
        rel = (time_ms - self.media.offset_ms) / 1000
        return self.grab(self.media.proxy, rel, self.ai_dir / name)

    # --- azioni ---------------------------------------------------------------------------

    def suggest(self, time_ms: int) -> dict[str, Any]:
        frame = self._frame(time_ms, f"suggest-{time_ms}.jpg")
        ideas = self.agent.suggest(self._context(time_ms, frame))
        return {"time_ms": time_ms, "frame": f"/media/ai/{frame.name}", "suggestions": ideas}

    def add(self, time_ms: int, prompt: str, kind: str, run: bool = True) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("scrivi una richiesta")
        if kind not in KINDS:
            raise ValueError("tipo non valido")
        with self.lock:
            data = self._load()
            n = len(data["requests"]) + 1
            req_id = f"ai_{n:04d}"
            frame = self._frame(time_ms, f"req-{n:04d}.jpg")
            req = {
                "id": req_id,
                "created_at": _now(),
                "time_ms": time_ms,
                "kind": kind,
                "prompt": prompt,
                "frame": f"/media/ai/{frame.name}",
                "status": "queued",
                "result": None,
                "note": None,
            }
            data["requests"].append(req)
            self._save(data)
        if run:
            self.run(req_id)
        return req

    def run(self, req_id: str) -> None:
        req = next((r for r in self.requests() if r["id"] == req_id), None)
        if req is None:
            raise KeyError(req_id)
        if req["status"] == "running":
            return
        self._update(req_id, status="running", note="Claude sta lavorando con Higgsfield…")
        self.executor.submit(self._work, req_id)

    def _work(self, req_id: str) -> None:
        req = next(r for r in self.requests() if r["id"] == req_id)
        frame = self.ai_dir / Path(req["frame"]).name
        try:
            out = self.agent.generate(
                self._context(req["time_ms"], frame), req["kind"], req["prompt"]
            )
        except AgentError as exc:
            self._update(req_id, status="error", note=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - un errore inatteso non deve fermare la coda
            self._update(req_id, status="error", note=f"errore inatteso: {exc}")
            return

        if out.get("status") != "done" or not out.get("urls"):
            self._update(
                req_id,
                status="error",
                note=out.get("note") or "Higgsfield non ha prodotto risultati",
                result=out,
            )
            return
        local = []
        for i, url in enumerate(out["urls"][:4], start=1):
            try:
                path = self.downloader(str(url), self.results_dir / f"{req_id}-{i}")
                local.append(f"/media/ai/results/{path.name}")
            except Exception as exc:  # noqa: BLE001
                out.setdefault("download_errors", []).append(f"{url}: {exc}")
        self._update(
            req_id,
            status="done",
            note=out.get("note"),
            result={**out, "local": local},
        )
