"""Server locale dell'editor (solo 127.0.0.1).

Legge timeline.json (mai modificata dall'editor) e scrive soltanto:
- overrides.json      (scelte dell'utente, con cronologia append-only);
- editor_state.json   (stato dell'interfaccia: quali proposte sono state riviste);
- ai_requests.json    (coda delle richieste "Potenzia con Higgsfield", con il frame).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import popups as pops
from ..brands import BrandError, BrandPack, list_brands
from ..models.io import read_model
from ..models.overrides import OverridesFile
from ..models.timeline import Segment, Timeline
from ..overrides import store
from ..overrides.resolve import effective_ranges, kept_ms
from ..paths import REPO_ROOT, TIMELINE_FILE
from ..styles import StyleError, StylePreset, list_styles, resolve_look
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


class BrandBody(BaseModel):
    id: str | None = None  # None = nessun brand (anteprima base)


class StyleBody(BaseModel):
    id: str | None = None  # None = nessuno stile (solo brand)


class PopupChatBody(BaseModel):
    prompt: str
    time_ms: int


class PopupItemBody(BaseModel):
    id: str
    action: str  # approve | reject | reset | delete | update
    fields: dict[str, Any] = {}


class PopupGenBody(BaseModel):
    id: str


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
    brands_root: Path | None = None,
    styles_root: Path | None = None,
    repo_root: Path = REPO_ROOT,
    auto_popups: bool = False,
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

    def state() -> dict[str, Any]:
        return _read_json(state_path, {})

    def update_state(**fields: Any) -> None:
        _write_json(state_path, {**state(), **fields})

    def reviewed() -> set[str]:
        return set(state().get("reviewed", []))

    def set_reviewed(decision_id: str | list[str], value: bool) -> None:
        ids = [decision_id] if isinstance(decision_id, str) else decision_id
        current = reviewed()
        if value:
            current.update(ids)
        else:
            current.difference_update(ids)
        update_state(reviewed=sorted(current))

    def brands() -> dict[str, BrandPack]:
        return {b.id: b for b in list_brands(brands_root)}

    def current_brand() -> BrandPack | None:
        return brands().get(state().get("brand") or "")

    def brand_payload(b: BrandPack) -> dict[str, Any]:
        return {
            **b.model_dump(mode="json"),
            "google_fonts_url": b.google_fonts_url(),
            "reference_images": [f"/media/ref/{b.id}/{i}" for i in range(len(reference_images(b)))],
        }

    def reference_images(b: BrandPack) -> list[Path]:
        found: list[Path] = []
        for ref in b.graphics.references:
            base = (repo_root / ref).resolve()
            if not base.is_relative_to(repo_root.resolve()):
                continue
            if base.is_file():
                found.append(base)
            elif base.is_dir():
                found += sorted(
                    p
                    for p in base.iterdir()
                    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                )
        return found[:24]

    def styles() -> dict[str, StylePreset]:
        return {s.id: s for s in list_styles(styles_root)}

    def current_style() -> StylePreset | None:
        return styles().get(state().get("style") or "")

    portrait = cam_video.display_height >= cam_video.display_width

    def look() -> dict[str, Any] | None:
        s = current_style()
        return resolve_look(s, current_brand(), portrait=portrait) if s else None

    def ai_context() -> str:
        parts = []
        if b := current_brand():
            parts.append(b.summary_for_ai())
        if s := current_style():
            parts.append(
                f"Stile di montaggio «{s.name}»: {s.description} Grafiche AI: {s.ai_graphics}"
            )
        return " ".join(parts)

    ai.brand = ai_context

    # --- pop-up ----------------------------------------------------------------------

    def word_rows(tl: Timeline) -> list[tuple[str, str, int]]:
        return [(w.id, w.text, w.start_ms) for w in tl.words if w.kind == "word"]

    def popups_file() -> pops.PopupsFile:
        """Stato dei pop-up: la prima volta aggiunge le proposte automatiche; collega le
        immagini Higgsfield appena pronte ai pop-up che le aspettavano."""
        data = pops.load(project_dir)
        sid = state().get("style")
        changed = (sid or "") not in data.seeded_styles
        data = pops.seed_from_ai_requests(data, project_dir, sid)
        done = {
            r["id"]: r
            for r in ai.requests()
            if r.get("status") == "done" and (r.get("result") or {}).get("local")
        }
        items = []
        for x in data.items:
            req = done.get(x.ai_request or "")
            if req and not x.image:
                name = req["result"]["local"][0].rsplit("/", 1)[-1]
                x = x.model_copy(update={"image": f"ai/results/{name}"})
                changed = True
            items.append(x)
        data = data.model_copy(update={"items": items})
        if changed:
            pops.save(project_dir, data)
        return data

    def popups_payload() -> list[dict[str, Any]]:
        reqs = {r["id"]: r for r in ai.requests()}
        sid = state().get("style")
        out = []
        for x in pops.sorted_items(popups_file()):
            if not x.visible_for(sid):
                continue  # proposte fatte per un altro stile
            d = x.model_dump(mode="json")
            d["image_url"] = (
                "/media/ai/results/" + x.image.rsplit("/", 1)[-1]
                if x.image and x.image.startswith("ai/results/")
                else None
            )
            d["image_status"] = (reqs.get(x.ai_request or "") or {}).get("status")
            out.append(d)
        return out

    def edited_ms() -> int:
        tl = timeline()
        return kept_ms(effective_ranges(tl, overrides(tl)))

    def popup_prompt(request: str | None = None, time_ms: int = 0) -> str:
        s = current_style()
        common = {
            "style_id": s.id if s else None,
            "style_name": s.name if s else "nessuno (usa la logica premium)",
            "words": word_rows(timeline()),
            "data": popups_file(),
            "duration_ms": edited_ms(),
        }
        if request is None:
            return pops.suggest_prompt(**common)
        return pops.chat_prompt(**common, request=request, time_ms=time_ms)

    popup_lock = threading.Lock()

    def run_popup_ops(prompt: str, *, automatic: bool) -> str:
        """Chiede a Claude le operazioni sui pop-up e le applica. Le proposte automatiche
        rispettano i limiti di parsimonia dello stile; le richieste in chat no (le chiedi tu)."""
        sid = state().get("style")
        try:
            ops = ai.agent.ask_json(prompt)
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from exc
        words = {wid: ms for wid, _, ms in word_rows(timeline())}
        count, gap = pops.limits(sid, edited_ms())
        with popup_lock:
            current = popups_file()
            try:
                new, log = pops.apply_ops(
                    current, ops, "ai", words=words, style=sid,
                    min_gap_ms=gap if automatic else 0, max_count=count if automatic else None,
                )  # fmt: skip
            except pops.PopupError as exc:
                raise HTTPException(502, f"proposta di Claude non valida: {exc}") from exc
            if automatic and sid and sid not in new.suggested:
                new = new.model_copy(update={"suggested": [*new.suggested, sid]})
            pops.save(project_dir, new)
        msg = str(ops.get("message") or "").strip()
        skipped = [x for x in log if x.startswith("saltato")]
        if skipped:
            msg += f" ({len(skipped)} proposte scartate per non affollare il video.)"
        return msg.strip() or (", ".join(log) if log else "Nessuna modifica.")

    popup_job: dict[str, Any] = {}

    def maybe_auto_suggest() -> None:
        """Appena scegli uno stile, Claude propone da solo i pop-up (una volta per stile)."""
        sid = state().get("style")
        if not auto_popups or not sid or popup_job.get("status") == "running":
            return
        if sid in popups_file().suggested or popup_job.get(f"failed:{sid}"):
            return
        popup_job.update(status="running", style=sid, message=None)

        def work() -> None:
            try:
                msg = run_popup_ops(popup_prompt(), automatic=True)
                popup_job.update(status="done", message=msg)
            except HTTPException as exc:
                popup_job.update(status="error", message=str(exc.detail))
                popup_job[f"failed:{sid}"] = True

        threading.Thread(target=work, daemon=True).start()

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
            "brand": brand_payload(b) if (b := current_brand()) else None,
            "brands": [{"id": b.id, "name": b.name} for b in brands().values()],
            "style": look(),
            "styles": [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in styles().values()
            ],
            "hook": state().get("hook"),
            "popups": popups_payload(),
            "popup_job": {k: v for k, v in popup_job.items() if not k.startswith("failed:")},
        }

    def fail(exc: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/project")
    def get_project() -> JSONResponse:
        maybe_auto_suggest()
        try:
            return JSONResponse(payload())
        except BrandError as exc:
            raise HTTPException(500, f"brand pack non valido: {exc}") from exc
        except StyleError as exc:
            raise HTTPException(500, f"preset di stile non valido: {exc}") from exc

    @app.post("/api/brand")
    def post_brand(body: BrandBody) -> JSONResponse:
        if body.id is not None and body.id not in brands():
            raise HTTPException(404, f"brand {body.id!r} non trovato in brands/")
        update_state(brand=body.id)
        return JSONResponse(payload())

    @app.post("/api/style")
    def post_style(body: StyleBody) -> JSONResponse:
        if body.id is not None and body.id not in styles():
            raise HTTPException(404, f"stile {body.id!r} non trovato in styles/")
        update_state(style=body.id)
        maybe_auto_suggest()
        return JSONResponse(payload())

    @app.get("/media/ref/{brand_id}/{index}")
    def brand_ref(brand_id: str, index: int) -> FileResponse:
        b = brands().get(brand_id)
        images = reference_images(b) if b else []
        if not 0 <= index < len(images):
            raise HTTPException(404)
        return FileResponse(images[index])

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

    @app.post("/api/popups/suggest")
    def popups_suggest() -> JSONResponse:
        msg = run_popup_ops(popup_prompt(), automatic=True)
        return JSONResponse({**payload(), "popup_message": msg})

    @app.post("/api/popups/chat")
    def popups_chat(body: PopupChatBody) -> JSONResponse:
        if not body.prompt.strip():
            raise HTTPException(400, "scrivi cosa vuoi cambiare")
        msg = run_popup_ops(popup_prompt(body.prompt.strip(), body.time_ms), automatic=False)
        return JSONResponse({**payload(), "popup_message": msg})

    @app.post("/api/popups/item")
    def popups_item(body: PopupItemBody) -> JSONResponse:
        data = popups_file()
        if not any(x.id == body.id for x in data.items):
            raise HTTPException(404, f"pop-up {body.id} non trovato")
        status = {"approve": "approved", "reject": "rejected", "reset": "proposed"}
        if body.action in status:
            ops: dict[str, Any] = {"update": [{"id": body.id, "status": status[body.action]}]}
        elif body.action == "delete":
            ops = {"remove": [body.id]}
        elif body.action == "update":
            ops = {"update": [{**body.fields, "id": body.id}]}
        else:
            raise HTTPException(400, f"azione {body.action!r} sconosciuta")
        words = {wid: ms for wid, _, ms in word_rows(timeline())}
        try:
            new, _ = pops.apply_ops(data, ops, "user", words=words)
        except pops.PopupError as exc:
            raise fail(exc) from exc
        pops.save(project_dir, new)
        return JSONResponse(payload())

    @app.post("/api/popups/generate")
    def popups_generate(body: PopupGenBody) -> JSONResponse:
        """Genera con Higgsfield l'immagine di un pop-up (solo su richiesta: costa crediti)."""
        data = popups_file()
        item = next((x for x in data.items if x.id == body.id), None)
        if item is None:
            raise HTTPException(404, f"pop-up {body.id} non trovato")
        if not item.image_prompt:
            raise HTTPException(400, "questo pop-up non ha un prompt per l'immagine")
        req = ai.add(item.at_ms, item.image_prompt, "image")
        new, _ = pops.apply_ops(
            data, {"update": [{"id": item.id, "ai_request": req["id"], "image": None}]}, "user"
        )
        pops.save(project_dir, new)
        return JSONResponse(payload())

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
