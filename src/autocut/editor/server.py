"""Server locale dell'editor (solo 127.0.0.1).

Legge timeline.json (mai modificata dall'editor) e scrive soltanto:
- overrides.json      (scelte dell'utente, con cronologia append-only);
- editor_state.json   (stato dell'interfaccia: quali proposte sono state riviste);
- ai_requests.json    (coda delle richieste "Potenzia con Higgsfield", con il frame).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..models.io import read_model
from ..models.overrides import OverridesFile
from ..models.timeline import Segment, Timeline
from ..overrides import store
from ..overrides.resolve import effective_ranges, kept_ms
from ..paths import TIMELINE_FILE
from .agent import AgentError, ClaudeAgent
from .ai_jobs import AiQueue
from .media import EditorMedia

STATIC_DIR = Path(__file__).parent / "static"
STATE_FILE = "editor_state.json"

SEGMENT_LABELS = {"head": "Silenzio iniziale", "tail": "Silenzio finale", "gap": "Pausa"}


class DecisionBody(BaseModel):
    id: str
    action: str  # flip | accept | reset


class GroupBody(BaseModel):
    id: str
    take_id: str | None = None


class ReviewedBody(BaseModel):
    ids: list[str]
    value: bool = True


class AiBody(BaseModel):
    time_ms: int
    prompt: str
    kind: str = "video"  # video | image | graphic
    run: bool = True  # False = solo in coda


class AiRunBody(BaseModel):
    id: str


class SuggestBody(BaseModel):
    time_ms: int


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _segment_label(seg: Segment) -> str:
    if seg.type == "speech":
        return "Parlato"
    if seg.id.startswith("gap:^-") and seg.id.endswith("-$"):
        return "Nessun parlato"
    if seg.id.startswith("gap:^-"):
        return SEGMENT_LABELS["head"]
    if seg.id.endswith("-$"):
        return SEGMENT_LABELS["tail"]
    return SEGMENT_LABELS["gap"]


def create_app(
    project_dir: Path,
    media: EditorMedia,
    *,
    agent: ClaudeAgent | None = None,
    queue: AiQueue | None = None,
) -> FastAPI:
    app = FastAPI(title="autocut editor", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def no_cache_ui(request, call_next):
        # L'interfaccia cambia spesso mentre la sviluppiamo: niente cache per pagina e API.
        response = await call_next(request)
        if not request.url.path.startswith("/media/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    tl_path = project_dir / TIMELINE_FILE
    state_path = project_dir / STATE_FILE
    ai_dir = project_dir / "work" / "ai"

    def timeline() -> Timeline:
        return read_model(tl_path, Timeline)

    first = timeline()
    cam_video = first.sources.camera.video
    ai = queue or AiQueue(
        project_dir,
        media,
        project=first.project.name,
        portrait=cam_video.display_height >= cam_video.display_width,
        words=lambda: timeline().words,
        agent=agent,
    )

    def overrides(tl: Timeline) -> OverridesFile:
        ov = store.load(project_dir, tl)
        reconciled, orphaned, restored = store.reconcile(ov, tl)
        if orphaned or restored:
            store.save(project_dir, reconciled)
        return reconciled

    def reviewed() -> set[str]:
        return set(_read_json(state_path, {}).get("reviewed", []))

    def set_reviewed(decision_id: str | list[str], value: bool) -> None:
        ids = [decision_id] if isinstance(decision_id, str) else decision_id
        current = reviewed()
        if value:
            current.update(ids)
        else:
            current.difference_update(ids)
        _write_json(state_path, {"reviewed": sorted(current)})

    def payload() -> dict[str, Any]:
        tl = timeline()
        ov = overrides(tl)
        seen = reviewed()
        eff = effective_ranges(tl, ov)

        decisions = []
        for seg in tl.segments:
            o = ov.overrides.get(seg.id)
            active = o if o is not None and o.status == "active" else None
            if seg.state != "remove" and active is None:
                continue
            decisions.append(
                {
                    "id": seg.id,
                    "kind": "segment",
                    "label": _segment_label(seg),
                    "type": seg.type,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "proposed": seg.state,
                    "effective": active.value["state"] if active else seg.state,
                    "overridden": active is not None,
                    "reason": seg.reason,
                    "data": seg.data,
                    "reviewed": seg.id in seen,
                }
            )

        groups = []
        for g in tl.repeat_groups:
            o = ov.overrides.get(g.id)
            active = o if o is not None and o.status == "active" else None
            chosen = (
                active.value.get("take_id")
                if active
                else (g.proposal.take_id if g.proposal else None)
            )
            groups.append(
                {
                    **g.model_dump(mode="json"),
                    "chosen": chosen,
                    "overridden": active is not None,
                    "reviewed": g.id in seen,
                }
            )

        orphans = [o.model_dump(mode="json") for o in ov.overrides.values() if o.status == "orphan"]
        undoable = store.last_undoable(ov)
        start = media.offset_ms
        return {
            "project": tl.project.name,
            "timeline": tl.model_dump(mode="json"),
            "decisions": decisions,
            "groups": groups,
            "orphans": orphans,
            "effective": [r.to_dict() for r in eff],
            "summary": {
                "raw_ms": media.duration_ms,
                "kept_ms": kept_ms(eff),
                "overrides": sum(1 for o in ov.overrides.values() if o.status == "active"),
                "history": len(ov.history),
                "can_undo": undoable is not None,
            },
            "media": {
                "video_url": "/media/video",
                "offset_ms": start,
                "duration_ms": media.duration_ms,
                "thumb_interval_ms": media.thumb_interval_ms,
                "thumb_count": media.thumb_count,
                "waveform_url": "/media/waveform",
            },
            "ai_requests": ai.requests(),
        }

    def fail(exc: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/project")
    def get_project() -> JSONResponse:
        return JSONResponse(payload())

    @app.post("/api/decision")
    def post_decision(body: DecisionBody) -> JSONResponse:
        tl = timeline()
        ov = overrides(tl)
        target = store.find_target(tl, body.id)
        if not isinstance(target, Segment):
            raise HTTPException(404, f"segmento {body.id} non trovato")
        try:
            if body.action == "flip":
                o = ov.overrides.get(body.id)
                if o is not None and o.status == "active":
                    ov = store.clear(ov, body.id)
                else:
                    other = "keep" if target.state == "remove" else "remove"
                    ov = store.set_value(ov, tl, body.id, {"state": other})
                set_reviewed(body.id, True)
            elif body.action == "accept":
                ov = store.clear(ov, body.id)
                set_reviewed(body.id, True)
            elif body.action == "reset":
                ov = store.clear(ov, body.id)
                set_reviewed(body.id, False)
            else:
                raise HTTPException(400, f"azione sconosciuta: {body.action}")
        except store.OverrideError as exc:
            raise fail(exc) from exc
        store.save(project_dir, ov)
        return JSONResponse(payload())

    @app.post("/api/group")
    def post_group(body: GroupBody) -> JSONResponse:
        tl = timeline()
        try:
            ov = store.set_value(overrides(tl), tl, body.id, {"take_id": body.take_id})
        except store.OverrideError as exc:
            raise fail(exc) from exc
        store.save(project_dir, ov)
        set_reviewed(body.id, True)
        return JSONResponse(payload())

    @app.post("/api/reviewed")
    def post_reviewed(body: ReviewedBody) -> JSONResponse:
        tl = timeline()
        known = {s.id for s in tl.segments} | {g.id for g in tl.repeat_groups}
        unknown = [i for i in body.ids if i not in known]
        if unknown:
            raise HTTPException(404, f"proposte sconosciute: {', '.join(unknown[:3])}")
        set_reviewed(body.ids, body.value)
        return JSONResponse(payload())

    @app.post("/api/undo")
    def post_undo() -> JSONResponse:
        tl = timeline()
        current = overrides(tl)
        entry = store.last_undoable(current)
        try:
            ov = store.undo(current, tl)
        except store.OverrideError as exc:
            raise fail(exc) from exc
        store.save(project_dir, ov)
        if entry is not None:
            set_reviewed(entry.target_id, False)  # la scelta annullata torna da rivedere
        return JSONResponse(payload())

    @app.get("/api/ai-status")
    def ai_status(refresh: bool = False) -> JSONResponse:
        return JSONResponse(ai.agent.status(refresh=refresh))

    @app.post("/api/ai-suggest")
    def ai_suggest(body: SuggestBody) -> JSONResponse:
        try:
            return JSONResponse(ai.suggest(body.time_ms))
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/ai-requests")
    def post_ai(body: AiBody) -> JSONResponse:
        try:
            ai.add(body.time_ms, body.prompt, body.kind, run=body.run)
        except ValueError as exc:
            raise fail(exc) from exc
        return JSONResponse(payload())

    @app.post("/api/ai-requests/run")
    def run_ai(body: AiRunBody) -> JSONResponse:
        try:
            ai.run(body.id)
        except KeyError as exc:
            raise HTTPException(404, f"richiesta {body.id} non trovata") from exc
        return JSONResponse(payload())

    @app.get("/media/video")
    def video() -> FileResponse:
        return FileResponse(media.proxy, media_type="video/mp4")

    @app.get("/media/waveform")
    def waveform() -> FileResponse:
        return FileResponse(media.waveform, media_type="application/json")

    @app.get("/media/thumbs/{index}.jpg")
    def thumb(index: int) -> FileResponse:
        path = media.thumbs_dir / f"{index:05d}.jpg"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/media/ai/{name}")
    def ai_frame(name: str) -> FileResponse:
        path = (ai_dir / name).resolve()
        if path.parent != ai_dir.resolve() or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/media/ai/results/{name}")
    def ai_result(name: str) -> FileResponse:
        base = (ai_dir / "results").resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/")
    def index() -> HTMLResponse:
        # Versione = data di modifica dei file: il browser ricarica CSS/JS quando cambiano.
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for name in ("styles.css", "app.js"):
            version = int((STATIC_DIR / name).stat().st_mtime)
            html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
        return HTMLResponse(html)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
