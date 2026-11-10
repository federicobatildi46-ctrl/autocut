"""Server locale dell'editor (solo 127.0.0.1).

Legge timeline.json (mai modificata dall'editor) e scrive soltanto:
- overrides.json      (scelte dell'utente, con cronologia append-only);
- editor_state.json   (stato dell'interfaccia: quali proposte sono state riviste);
- ai_requests.json    (coda delle richieste "Potenzia con Higgsfield", con il frame);
- popups.json e text_style.json (pop-up e testo personalizzato dei sottotitoli);
- work/images/ (foto cercate sul web o caricate, scontornate, pannello Immagini);
- cuts.json (divisioni e pezzi tolti a mano) e audio.json (volumi e suoni, pannello Audio);
- covers.json e work/covers/ (copertine Shorts e YouTube della finestra Esporta).
Annulla / Ripeti valgono per tutto (history.py).
"""

from __future__ import annotations

import base64
import itertools
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import audio_mix as amix
from .. import covers as cov
from .. import effects as fx
from .. import emoji as emo
from .. import filters as flt
from .. import images as imgs
from .. import manual_cuts as cutmod
from .. import popups as pops
from .. import text_style as txt
from .. import vfx as vfxmod
from ..brands import BrandError, BrandPack, list_brands
from ..models.io import read_model
from ..models.overrides import OverridesFile
from ..models.timeline import Segment, Timeline
from ..overrides import store
from ..overrides.resolve import effective_ranges, kept_ms
from ..paths import REPO_ROOT, TIMELINE_FILE
from ..render.preview import LIBRARY_DIR, _catalog, sfx_loudness
from ..styles import StyleError, StylePreset, list_styles, resolve_look
from .agent import AgentError, ClaudeAgent
from .ai_jobs import AiQueue
from .history import History, HistoryError
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


class StickerBody(BaseModel):
    kind: str  # emoji | text | image
    at_ms: int
    emoji: str | None = None
    title: str = ""
    image: str | None = None  # relativo a work/ (es. ai/results/x.png, images/img_0001.png)
    cutout: bool | None = None  # foto scontornata (pannello Immagini)
    x_pct: float = 50
    y_pct: float = 40
    size: str = "medium"
    scale: float = 1.0
    layer: str = "under_text"
    duration_ms: int = 2000
    sound: bool = True


class ImageAddBody(BaseModel):
    url: str | None = None  # immagine trovata sul web
    thumb: str | None = None  # miniatura (se il sito blocca l'originale)
    page: str = ""
    title: str = ""
    source: str = ""
    license: str | None = None
    data: str | None = None  # oppure caricata dal PC: data URL base64
    redo: str | None = None  # oppure rifai un'immagine già preparata (images/img_0001.png)
    cutout: bool = True
    quality: str = "fast"  # fast (~2 s) | best (~20 s)


class CutBody(BaseModel):
    action: str  # split | unsplit | remove | restore
    ms: int | None = None
    start: int | None = None
    end: int | None = None


class AudioBody(BaseModel):
    target: str  # mix | sound | add | remove | reset
    item: str | None = None
    fields: dict[str, Any] = {}


class CoverConceptBody(BaseModel):
    hint: str = ""  # di cosa parla il video, in parole del creator


class CoverSaveBody(BaseModel):
    concept: dict[str, Any] = {}
    person: dict[str, Any] = {}


class CoverRatioBody(BaseModel):
    ratio: str
    index: int | None = None


class CoverFaceBody(BaseModel):
    data: str  # data URL base64 della foto del volto
    name: str = ""


class VfxBody(BaseModel):
    start_ms: int = Field(ge=0)
    dur_ms: int = Field(ge=500, le=3000)
    request: str = Field(min_length=1, max_length=1200)
    protect: bool = True
    quality: str = "auto"  # automatica: Claude sceglie ricetta e modello


class VfxRetryBody(BaseModel):
    use_fix: bool = True


class VfxAnswerBody(BaseModel):
    answers: list[str] = Field(default_factory=list, max_length=3)  # vuoto = «genera così»


class VfxEnableBody(BaseModel):
    enabled: bool


class FilterBody(BaseModel):
    preset: str | None = None
    values: dict[str, float] = {}
    reset: bool = False


class EffectBody(BaseModel):
    target: str  # captions | sticker_default | sticker | transition | all_transitions
    item: str | None = None  # id pop-up o id del punto di transizione
    phase: str | None = None  # in | out | loop
    spec: dict[str, Any] | None = None  # {type, ms, speed}; None = valore dello stile


class TextBody(BaseModel):
    scene: str | None = None  # None = tutti i sottotitoli; altrimenti id della prima parola
    fields: dict[str, Any] = {}
    reset: bool = False  # True = toglie le scelte (di tutti o della scena) prima di applicare


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
    image_search: Any = None,  # test: ricerca finta
    image_fetch: Any = None,  # test: download finto
    image_masker: Any = None,  # test: scontorno finto
    image_runner: Any = None,  # test: esegue i lavori subito (default: thread)
    sfx_catalog: dict[str, list[dict[str, Any]]] | None = None,  # test: libreria suoni finta
    sfx_root: Path | None = None,  # test: cartella dei suoni
    cover_runner: Any = None,  # test: Higgsfield finto
    cover_download: Any = None,  # test: download finto
    cover_still: Any = None,  # test: render Remotion finto
    export_runner: Any = None,  # test: render finto del video intero
    vfx_runner: Any = None,  # test: esegue subito il lavoro «Genera con Higgsfield» (finto)
    cover_grab: Any = None,  # test: fotogramma finto
    brands_root: Path | None = None,
    styles_root: Path | None = None,
    repo_root: Path = REPO_ROOT,
    auto_popups: bool = False,
    keepalive: bool = False,  # rinnova la sessione Higgsfield ogni 20 minuti
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
    hist = History(project_dir, lambda: read_model(tl_path, Timeline), STATE_FILE)
    no_history = {"/api/history/undo", "/api/history/redo", "/api/undo", "/api/images/add"}

    @app.middleware("http")
    async def track_history(request, call_next):
        path = request.url.path
        if request.method != "POST" or not path.startswith("/api/") or path in no_history:
            return await call_next(request)
        before = hist.snapshot()
        response = await call_next(request)
        if response.status_code < 400:
            hist.record(before, hist.snapshot())
        return response

    state_path = project_dir / STATE_FILE
    ai_dir = project_dir / "work" / "ai"
    work_dir = project_dir / "work"
    img_dir = work_dir / imgs.IMAGES_DIR

    def eff_of(tl: Timeline, ov: OverridesFile | None) -> list:
        return cutmod.apply(effective_ranges(tl, ov), cutmod.load(project_dir))

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

    def style_look() -> dict[str, Any] | None:
        s = current_style()
        return resolve_look(s, current_brand(), portrait=portrait) if s else None

    def text_for_style() -> txt.StyleText:
        return txt.for_style(txt.load(project_dir), state().get("style"))

    def look() -> dict[str, Any] | None:
        """Look dello stile con le scelte del pannello Testo già applicate."""
        base = style_look()
        if not base:
            return None
        lk = txt.apply_to_look(base, text_for_style())
        return flt.apply_to_look(lk, flt.for_style(flt.load(project_dir), state().get("style")))

    def text_payload(lk: dict[str, Any] | None) -> dict[str, Any]:
        st = text_for_style()
        caps = lk["captions"] if lk else None
        return {
            **txt.catalog_payload(state().get("style")),
            "base": st.base.model_dump(exclude_none=True),
            "scenes": {k: v.model_dump(exclude_none=True) for k, v in st.scenes.items()},
            # campi look.captions che ogni scena cambia (già risolti, come nel render)
            "resolved": {k: txt.scene_overrides(caps, v) for k, v in st.scenes.items()}
            if caps
            else {},
        }

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

    def image_url(rel: str | None) -> str | None:
        if not rel:
            return None
        name = rel.rsplit("/", 1)[-1]
        if rel.startswith("ai/results/"):
            return "/media/ai/results/" + name
        if rel.startswith(imgs.IMAGES_DIR + "/"):
            f = img_dir / name
            v = int(f.stat().st_mtime) if f.is_file() else 0
            return f"/media/images/{name}?v={v}"  # cambia quando rifai lo scontorno
        return None

    def popups_payload() -> list[dict[str, Any]]:
        reqs = {r["id"]: r for r in ai.requests()}
        sid = state().get("style")
        out = []
        for x in pops.sorted_items(popups_file()):
            if not x.visible_for(sid):
                continue  # proposte fatte per un altro stile
            d = x.model_dump(mode="json")
            d["image_url"] = image_url(x.image)
            d["image_status"] = (reqs.get(x.ai_request or "") or {}).get("status")
            d["emoji_imgs"] = emo.images_for(x.emoji) if x.emoji else None
            out.append(d)
        return out

    def sticker_library() -> dict[str, Any]:
        sid = state().get("style") or "viral"
        lib = pops.STICKERS.get(sid, pops.STICKERS["viral"])
        results = ai_dir / "results"
        images = (
            sorted(
                x.name
                for x in results.iterdir()
                if x.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            )
            if results.is_dir()
            else []
        )
        return {
            **lib,
            "images": [
                {"image": f"ai/results/{n}", "url": f"/media/ai/results/{n}"} for n in images
            ],
        }

    def effect_points(tl: Timeline, eff: list) -> list[dict[str, Any]]:
        return fx.boundaries(
            tl, eff, video=media.proxy, offset_ms=media.offset_ms,
            cache_path=project_dir / "work" / "scenes.json",
        )  # fmt: skip

    def effects_payload(tl: Timeline, eff: list) -> dict[str, Any]:
        sid = state().get("style")
        res = fx.resolved(sid, fx.for_style(fx.load(project_dir), sid))
        points = [{**b, "transition": fx.transition_for(res, b)} for b in effect_points(tl, eff)]
        return {"anims": fx.ANIMS, "transitions": fx.TRANSITIONS, "style": sid,
                "resolved": res, "points": points}  # fmt: skip

    catalog = sfx_catalog if sfx_catalog is not None else _catalog()
    sfx_dir = sfx_root or LIBRARY_DIR
    loud = (lambda s: None) if sfx_catalog is not None else sfx_loudness
    plan_cache: dict[str, Any] = {}

    def audio_style() -> amix.StyleAudio:
        return amix.for_style(amix.load(project_dir), state().get("style"))

    def sound_plan(tl: Timeline, eff: list, lk: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Suoni automatici dello stile su tutto il video (in cache finché nulla cambia)."""
        if lk is None or not catalog:
            return []
        files = ["popups.json", "text_style.json", "effects.json", STATE_FILE, "overrides.json",
                 "cuts.json", TIMELINE_FILE]  # fmt: skip
        key = json.dumps([state().get("style"), state().get("brand"), [
            (project_dir / f).stat().st_mtime_ns if (project_dir / f).exists() else 0
            for f in files
        ]])  # fmt: skip
        if plan_cache.get("key") != key:
            sid = state().get("style")
            plan_cache["plan"] = amix.auto_plan(
                end_ms=max((r.end_ms for r in eff), default=0),
                project_dir=project_dir, tl=tl, eff=eff, look=lk,
                hook_text=state().get("hook"), catalog=catalog, loudness=loud,
                scenes=text_for_style().scenes,
                effects=fx.resolved(sid, fx.for_style(fx.load(project_dir), sid)),
                points=effect_points(tl, eff),
            )  # fmt: skip
            plan_cache["key"] = key
        return plan_cache["plan"]

    def voice_norm_db(lk: dict[str, Any] | None) -> float:
        """La stessa normalizzazione della voce del render (se già misurata)."""
        p = project_dir / "work" / "render" / "voice.json"
        if lk is None or not p.exists():
            return 0.0
        lufs = json.loads(p.read_text(encoding="utf-8")).get("lufs")
        if lufs is None:
            return 0.0
        return round(max(-10.0, min(30.0, lk["sound"]["voice_lufs"] - lufs)), 1)

    def audio_payload(tl: Timeline, eff: list, lk: dict[str, Any] | None) -> dict[str, Any]:
        sa = audio_style()
        sounds = amix.resolve(sound_plan(tl, eff, lk), sa, lk, catalog, loud)
        for s in sounds:
            s["url"] = "/media/sfx/" + s["file"]
        return {
            "style": state().get("style"),
            **sa.model_dump(mode="json", exclude={"sounds", "added"}),
            "voice_norm_db": voice_norm_db(lk),
            "sounds": sounds,
            "library": amix.library(catalog),
        }

    covers_dir = project_dir / "work" / cov.COVERS_DIR
    cover_job: dict[str, Any] = {}
    export_job: dict[str, Any] = {}
    renders_dir = project_dir / "renders"

    def export_payload() -> dict[str, Any]:
        files = sorted(renders_dir.glob("*-finale-*.mp4"), key=lambda p: p.stat().st_mtime) if (
            renders_dir.is_dir()) else []  # fmt: skip
        last = files[-1] if files else None
        return {
            "job": dict(export_job),
            "last": {"name": last.name, "url": f"/media/export/{last.name}",
                     "mb": round(last.stat().st_size / 1e6, 1)} if last else None,
        }  # fmt: skip

    def run_export() -> None:
        """Render del video intero con tutto (tagli, testo, sticker, effetti, audio, filtri),
        poi la copertina scelta dentro il file MP4."""
        from ..render.step import run_style_preview

        sid = state().get("style")
        try:
            tl = timeline()
            run = export_runner or run_style_preview
            res = run(
                project_dir.name, style_id=None, brand_id=None, at_ms=0, before_ms=0,
                after_ms=tl.sources.camera.duration_ms, clip=True,
                projects_root=project_dir.parent,
                log=lambda s: export_job.update(log=s.strip()[:160]),
            )  # fmt: skip
            export_job.update(phase="cover")
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            final = renders_dir / f"{project_dir.name}-{sid}-finale-{stamp}.mp4"
            sc = cov.for_style(cov.load(project_dir), sid)
            ratio = "9:16" if portrait else "16:9"
            chosen = sc.versions.get(ratio, [])
            idx = sc.chosen.get(ratio, len(chosen) - 1)
            cover = covers_dir / chosen[idx].file if chosen and 0 <= idx < len(chosen) else None
            cov.attach_cover(Path(res.output), cover, final)
            export_job.update(status="done", phase="done", file=final.name,
                              cover=bool(cover and cover.is_file()))  # fmt: skip
        except Exception as exc:  # qualsiasi errore va mostrato nella finestra
            export_job.update(status="error", error=str(exc) or exc.__class__.__name__)

    # --- Genera con Higgsfield: effetti AI dentro la ripresa vera (skill higgsfield-vfx) ---

    def vfx_payload() -> dict[str, Any]:
        shots = []
        for s in vfxmod.load(project_dir).shots:
            base = f"/media/vfx/{s.id}/"
            shots.append({
                **s.model_dump(exclude={"fix_prompt"}),
                "final_url": base + s.final if s.final else None,
                "sheet_url": base + s.sheet if s.sheet else None,
                "frame_url": base + "frame.jpg",
                "phase_label": vfxmod.PHASES.get(s.phase, s.phase),
            })  # fmt: skip
        return {
            "shots": shots,
            "max_ms": vfxmod.MAX_EFFECT_MS,
            "qualities": {k: {"label": q["label"], "credits": q["credits"],
                              "usd": vfxmod.api_usd(k, (1080, 1920), vfxmod.GEN_MS / 1000)
                              if q.get("api") else 0}
                          for k, q in vfxmod.QUALITIES.items()},
            "recipes": {k: {"label": r["label"], "credits": r["credits"], "protect": r["protect"]}
                        for k, r in vfxmod.RECIPES.items()},
            "ref_credits": 0.12,
        }  # fmt: skip

    def start_vfx(shot_id: str) -> None:
        def job() -> None:
            vfxmod.run_shot(project_dir, shot_id, tl=timeline(), agent=ai.agent)

        if vfx_runner is not None:
            vfx_runner(project_dir, shot_id)
        else:
            threading.Thread(target=job, daemon=True).start()

    @app.post("/api/vfx")
    def vfx_create(body: VfxBody) -> JSONResponse:
        if any(s.status == "running" for s in vfxmod.load(project_dir).shots):
            raise HTTPException(409, "c'è già una generazione in corso: aspetta che finisca")
        try:
            shot = vfxmod.add(
                project_dir, start_ms=body.start_ms, dur_ms=body.dur_ms, request=body.request,
                protect=body.protect, quality=body.quality,
                camera_ms=timeline().sources.camera.duration_ms,
            )  # fmt: skip
        except vfxmod.VfxError as exc:
            raise HTTPException(400, str(exc)) from exc
        start_vfx(shot.id)
        return JSONResponse(payload())

    @app.post("/api/vfx/{shot_id}/retry")
    def vfx_retry(shot_id: str, body: VfxRetryBody) -> JSONResponse:
        try:
            vfxmod.retry(project_dir, shot_id, body.use_fix)
        except vfxmod.VfxError as exc:
            raise HTTPException(400, str(exc)) from exc
        start_vfx(shot_id)
        return JSONResponse(payload())

    @app.post("/api/vfx/{shot_id}/answer")
    def vfx_answer(shot_id: str, body: VfxAnswerBody) -> JSONResponse:
        if any(s.status == "running" for s in vfxmod.load(project_dir).shots):
            raise HTTPException(409, "c'è già una generazione in corso: aspetta che finisca")
        try:
            vfxmod.answer(project_dir, shot_id, [a[:300] for a in body.answers])
        except vfxmod.VfxError as exc:
            raise HTTPException(400, str(exc)) from exc
        start_vfx(shot_id)
        return JSONResponse(payload())

    @app.post("/api/vfx/{shot_id}/enable")
    def vfx_enable(shot_id: str, body: VfxEnableBody) -> JSONResponse:
        try:
            s = vfxmod.get(project_dir, shot_id)
            if body.enabled and not s.final:
                raise vfxmod.VfxError("la clip non è ancora pronta")
            vfxmod.edit(project_dir, shot_id, enabled=body.enabled)
        except vfxmod.VfxError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(payload())

    @app.post("/api/vfx/{shot_id}/delete")
    def vfx_delete(shot_id: str) -> JSONResponse:
        s = next((x for x in vfxmod.load(project_dir).shots if x.id == shot_id), None)
        if s is None:
            raise HTTPException(404, "clip AI non trovata")
        if s.status == "running":
            raise HTTPException(409, "sta ancora generando")
        vfxmod.remove(project_dir, shot_id)
        return JSONResponse(payload())

    @app.get("/media/vfx/{shot_id}/{name}")
    def vfx_file(shot_id: str, name: str) -> FileResponse:
        base = vfxmod.shot_dir(project_dir, shot_id).resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.suffix not in (".mp4", ".jpg", ".png"):
            raise HTTPException(404)
        return FileResponse(path)

    @app.post("/api/export/video")
    def export_video() -> JSONResponse:
        if state().get("style") is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        if export_job.get("status") == "running":
            raise HTTPException(409, "il video si sta già esportando")
        export_job.clear()
        export_job.update(status="running", phase="render", started=time.time())
        if export_runner is not None:
            run_export()  # test: subito
        else:
            threading.Thread(target=run_export, daemon=True).start()
        return JSONResponse(payload())

    @app.get("/media/export/{name}")
    def export_file(name: str) -> FileResponse:
        base = renders_dir.resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.suffix != ".mp4":
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4", filename=name)

    def covers_payload() -> dict[str, Any]:
        sid = state().get("style")
        data = cov.load(project_dir)
        sc = cov.for_style(data, sid)
        versions = {}
        for ratio in cov.RATIOS:
            versions[ratio] = [
                {**v.model_dump(mode="json"), "index": i,
                 "url": f"/media/covers/{v.file}?v={int((covers_dir / v.file).stat().st_mtime)}"}
                for i, v in enumerate(sc.versions.get(ratio, []))
                if (covers_dir / v.file).is_file()
            ]  # fmt: skip
        person = data.person.model_dump(mode="json")
        person["face_url"] = (
            f"/media/covers/{data.person.face}" if data.person.face
            and (covers_dir / data.person.face).is_file() else None
        )  # fmt: skip
        tl = timeline()
        lk = look()
        dflt = cov.default_frame_ms(eff_of(tl, overrides(tl)))
        frame = sc.concept.frame_ms if sc.concept.frame_ms is not None else dflt
        fonts = []
        if lk:
            fonts = [f for f in dict.fromkeys([(lk.get("hook") or {}).get("font") or "Lilita One",
                                               lk["captions"]["font"]]) if f]  # fmt: skip
        return {
            "style": sid,
            "mode": "viral" if sid == "viral" else "premium",
            "ready": sid in ("premium", "viral"),
            "ratios": ["9:16"] if sid == "viral" else list(cov.RATIOS),
            "default_frame_ms": dflt,
            "frame_url": f"/media/frame/{frame}",
            "accent_auto": cov.auto_accent(lk) if lk else "#FFB800",
            "fonts": fonts,
            "concept": sc.concept.model_dump(mode="json"),
            "versions": versions,
            "chosen": sc.chosen,
            "person": person,
            "job": dict(cover_job),
            "cost_hint": cov.COST_HINT,
        }

    def edited_ms() -> int:
        tl = timeline()
        return kept_ms(eff_of(tl, overrides(tl)))

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
        eff = eff_of(tl, ov)

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
                "can_undo": hist.can_undo,
                "can_redo": hist.can_redo,
                "can_undo_cut": undoable is not None,
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
            "style": (lk := look()),
            "styles": [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in styles().values()
            ],
            "hook": state().get("hook"),
            "text": text_payload(lk),
            "popups": popups_payload(),
            "stickers": sticker_library(),
            "images": imgs.library(work_dir),
            "effects": effects_payload(tl, eff),
            "cuts": cutmod.load(project_dir).model_dump(mode="json"),
            "audio": audio_payload(tl, eff, lk),
            "covers": covers_payload(),
            "export": export_payload(),
            "vfx": vfx_payload(),
            "filters": {
                **flt.for_style(flt.load(project_dir), state().get("style")).model_dump(),
                "presets": flt.PRESETS,
                "grade": lk["grade"] if lk else None,
                "style_grade": (sl := style_look()) and sl["grade"],
            },
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

    @app.post("/api/effects")
    def post_effects(body: EffectBody) -> JSONResponse:
        sid = state().get("style")
        if sid is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        data = fx.load(project_dir)
        try:
            if body.target == "all_transitions":
                tl = timeline()
                for b in effect_points(tl, eff_of(tl, overrides(tl))):
                    data = fx.update(data, sid, target="transition", item=b["id"], spec=body.spec)
            else:
                data = fx.update(data, sid, target=body.target, item=body.item,
                                 phase=body.phase, spec=body.spec)  # fmt: skip
        except (fx.EffectsError, ValueError) as exc:
            raise fail(exc) from exc
        fx.save(project_dir, data)
        return JSONResponse(payload())

    @app.post("/api/effects/suggest")
    def effects_suggest() -> JSONResponse:
        """Claude compone gli effetti dello stile: testo, sticker e transizioni."""
        s = current_style()
        if s is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        tl = timeline()
        points = effect_points(tl, eff_of(tl, overrides(tl)))
        items = [p for p in popups_payload() if p["status"] != "rejected"]
        prompt = fx.suggest_prompt(s.id, s.name, word_rows(tl), points, items)
        try:
            ops = ai.agent.ask_json(prompt)
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from exc
        data, note = fx.apply_suggestion(
            fx.load(project_dir), s.id, ops if isinstance(ops, dict) else {},
            sticker_ids={p["id"] for p in items}, point_ids={b["id"] for b in points},
        )  # fmt: skip
        fx.save(project_dir, data)
        out = payload()
        out["message"] = note or "Effetti scelti da Claude"
        return JSONResponse(out)

    @app.get("/anim.js")
    def anim_js() -> FileResponse:
        """Motore delle animazioni, lo stesso file usato dal render Remotion."""
        return FileResponse(repo_root / "motion" / "src" / "anim.js", media_type="text/javascript")

    @app.post("/api/text")
    def post_text(body: TextBody) -> JSONResponse:
        if current_style() is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        try:
            data = txt.update(
                txt.load(project_dir),
                state().get("style"),
                scene=body.scene,
                fields=body.fields,
                reset=body.reset,
                allowed=txt.allowed_fonts(style_look()),
            )
        except (txt.TextStyleError, ValueError) as exc:
            raise fail(exc) from exc
        txt.save(project_dir, data)
        return JSONResponse(payload())

    @app.get("/api/emoji")
    def emoji_set() -> JSONResponse:
        """Tastiera emoji (immagini stile iPhone in library/emoji, se presenti)."""
        idx = emo.index(emo.EMOJI_DIR)
        cats = [
            {"name": c["name"], "items": [{"e": i["e"], "img": i["img"]} for i in c["items"]]}
            for c in idx["categories"]
        ]
        return JSONResponse({"available": bool(cats), "categories": cats})

    @app.get("/media/emoji/{name}")
    def emoji_png(name: str) -> FileResponse:
        path = emo.EMOJI_DIR / "apple" / name
        if not emo.NAME_RE.match(name) or not path.is_file():
            raise HTTPException(404, "emoji non trovata")
        cache = {"Cache-Control": "max-age=86400"}
        return FileResponse(path, media_type="image/png", headers=cache)

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

    @app.post("/api/history/undo")
    def history_undo() -> JSONResponse:
        try:
            hist.undo()
        except HistoryError as exc:
            raise fail(exc) from exc
        return JSONResponse(payload())

    @app.post("/api/history/redo")
    def history_redo() -> JSONResponse:
        try:
            hist.redo()
        except HistoryError as exc:
            raise fail(exc) from exc
        return JSONResponse(payload())

    @app.post("/api/cuts")
    def post_cuts(body: CutBody) -> JSONResponse:
        """Dividi alla testina, togli o rimetti un pezzo (sopra le scelte del motore)."""
        data = cutmod.load(project_dir)
        try:
            if body.action in ("split", "unsplit"):
                if body.ms is None:
                    raise cutmod.CutError("manca l'istante")
                fn = cutmod.split if body.action == "split" else cutmod.unsplit
                data = fn(data, body.ms)
            elif body.action in ("remove", "restore"):
                if body.start is None or body.end is None:
                    raise cutmod.CutError("manca il pezzo")
                fn = cutmod.remove if body.action == "remove" else cutmod.restore
                data = fn(data, body.start, body.end)
            else:
                raise cutmod.CutError(f"azione {body.action!r} sconosciuta")
        except cutmod.CutError as exc:
            raise fail(exc) from exc
        cutmod.save(project_dir, data)
        return JSONResponse(payload())

    @app.post("/api/audio")
    def post_audio(body: AudioBody) -> JSONResponse:
        try:
            data = amix.update(
                amix.load(project_dir), state().get("style"), target=body.target,
                item=body.item, fields=body.fields, catalog=catalog,
            )  # fmt: skip
        except amix.AudioError as exc:
            raise fail(exc) from exc
        amix.save(project_dir, data)
        return JSONResponse(payload())

    @app.get("/media/sfx/{path:path}")
    def sfx_file(path: str) -> FileResponse:
        base = sfx_dir.resolve()
        f = (base / path).resolve()
        if not f.is_relative_to(base) or not f.is_file() or f.suffix not in {".mp3", ".wav"}:
            raise HTTPException(404)
        return FileResponse(f, media_type="audio/mpeg" if f.suffix == ".mp3" else "audio/wav")

    # --- copertine (finestra Esporta) -------------------------------------------------

    @app.post("/api/covers/concept")
    def covers_concept(body: CoverConceptBody) -> JSONResponse:
        """Claude propone frase e sfondo dal parlato (e da quello che dice il creator)."""
        s = current_style()
        if s is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        words = " ".join(w.text for w in timeline().words if w.kind == "word")
        data = cov.load(project_dir)
        sc = cov.for_style(data, s.id)
        prompt = (cov.viral_concept_prompt(words, body.hint.strip()) if s.id == "viral"
                  else cov.concept_prompt(s.name, words, body.hint.strip()))  # fmt: skip
        try:
            raw = ai.agent.ask_json(prompt)
            concept = cov.clean_concept(raw if isinstance(raw, dict) else {}, sc.concept)
        except (AgentError, cov.CoverError) as exc:
            raise HTTPException(502, str(exc)) from exc
        if body.hint.strip():
            concept = concept.model_copy(update={"topic": body.hint.strip()[:400]})
        sc = sc.model_copy(update={"concept": concept})
        cov.save(project_dir, cov.with_style(data, s.id, sc))
        return JSONResponse(payload())

    @app.post("/api/covers/save")
    def covers_save(body: CoverSaveBody) -> JSONResponse:
        sid = state().get("style")
        data = cov.load(project_dir)
        sc = cov.for_style(data, sid)
        try:
            concept = cov.clean_concept(body.concept, sc.concept, allow_empty=True)
            person = cov.Person.model_validate(
                {**data.person.model_dump(), **{k: v for k, v in body.person.items()
                                                if k in ("name", "soul_id")}}
            )  # fmt: skip
        except (cov.CoverError, ValueError) as exc:
            raise fail(exc) from exc
        data = cov.with_style(data, sid, sc.model_copy(update={"concept": concept}))
        cov.save(project_dir, data.model_copy(update={"person": person}))
        return JSONResponse(payload())

    @app.post("/api/covers/face")
    def covers_face(body: CoverFaceBody) -> JSONResponse:
        """Foto del volto (tua o del cliente) per tenere la stessa identità."""
        try:
            raw = base64.b64decode(body.data.split(",", 1)[-1])
            info = imgs.prepare(raw, covers_dir / "face.png", cutout=False)
        except (imgs.ImageError, ValueError) as exc:
            raise fail(exc) from exc
        del info
        data = cov.load(project_dir)
        person = data.person.model_copy(update={"face": "face.png"})
        cov.save(project_dir, data.model_copy(update={"person": person}))
        return JSONResponse(payload())

    def run_cover(ratio: str) -> None:
        sid = state().get("style")
        data = cov.load(project_dir)
        sc = cov.for_style(data, sid)
        name = cov.next_file(covers_dir, sid, ratio)
        face = covers_dir / data.person.face if data.person.face else None
        try:
            if sid == "viral":  # in locale: fotogramma + frase d'esordio (gratis)
                cover_job.update(phase="render")
                tl = timeline()
                ms = sc.concept.frame_ms
                if ms is None:
                    ms = cov.default_frame_ms(eff_of(tl, overrides(tl)))
                lk = look()
                if lk is None:
                    raise cov.CoverError("scegli prima lo stile")
                cov.render_viral(project_dir, tl, lk, sc.concept, ms, covers_dir / name,
                                 still=cover_still, grab=cover_grab)  # fmt: skip
                job = None
            else:
                job = cov.generate(
                    sc.concept, ratio, data.person, face, covers_dir / name,
                    runner=cover_runner or cov.cli_runner, download=cover_download,
                    progress=lambda ph: cover_job.update(phase=ph),
                )  # fmt: skip
            version = cov.Version(file=name, job_id=job, title=sc.concept.title,
                                  at=datetime.now(UTC).isoformat(timespec="seconds"))  # fmt: skip
            cov.save(project_dir, cov.add_version(cov.load(project_dir), sid, ratio, version))
            cover_job.update(status="done", phase="done")
        except Exception as exc:  # qualsiasi errore va mostrato nella finestra
            cover_job.update(status="error", error=str(exc) or exc.__class__.__name__)

    @app.post("/api/covers/generate")
    def covers_generate(body: CoverRatioBody) -> JSONResponse:
        """Genera con Higgsfield (solo su clic dell'utente: costa crediti)."""
        if body.ratio not in cov.RATIOS:
            raise HTTPException(400, f"formato {body.ratio!r} non previsto")
        sid = state().get("style")
        if sid not in ("premium", "viral"):
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        if sid == "viral" and body.ratio != "9:16":
            raise HTTPException(400, "nello stile Viral la copertina è solo verticale (9:16)")
        if cover_job.get("status") == "running":
            raise HTTPException(409, "sto già generando una copertina: aspetta che finisca")
        if not cov.for_style(cov.load(project_dir), sid).concept.title:
            raise HTTPException(400, "scrivi prima la frase della copertina")
        cover_job.clear()
        cover_job.update(status="running", ratio=body.ratio, phase="queued")
        if cover_runner is not None or cover_still is not None:
            run_cover(body.ratio)  # test: subito
        else:
            threading.Thread(target=run_cover, args=(body.ratio,), daemon=True).start()
        return JSONResponse(payload())

    @app.post("/api/covers/choose")
    def covers_choose(body: CoverRatioBody) -> JSONResponse:
        sid = state().get("style")
        try:
            data = cov.choose(cov.load(project_dir), sid, body.ratio, body.index or 0)
        except cov.CoverError as exc:
            raise fail(exc) from exc
        cov.save(project_dir, data)
        return JSONResponse(payload())

    @app.get("/media/frame/{ms}")
    def frame_at(ms: int) -> FileResponse:
        """Anteprima del fotogramma scelto per la copertina (dal video di anteprima)."""
        dest = project_dir / "work" / "render" / f"frame-preview-{ms}.jpg"
        if not dest.exists():
            try:
                (cover_grab or cov.grab_frame)(media.proxy, max(0, ms - media.offset_ms), dest)
            except cov.CoverError as exc:
                raise HTTPException(404, str(exc)) from exc
        return FileResponse(dest, media_type="image/jpeg")

    @app.get("/media/covers/{name}")
    def cover_file(name: str) -> FileResponse:
        base = covers_dir.resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.suffix not in {".png", ".jpg"}:
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/api/ai-status")
    def ai_status(refresh: bool = False) -> JSONResponse:
        return JSONResponse(ai.agent.status(refresh=refresh))

    @app.post("/api/filters")
    def post_filters(body: FilterBody) -> JSONResponse:
        if current_style() is None:
            raise HTTPException(400, "scegli prima uno stile (Viral o Premium) dal menu in alto")
        try:
            data = flt.update(flt.load(project_dir), state().get("style"), preset=body.preset,
                              values=body.values, reset=body.reset)  # fmt: skip
        except flt.FilterError as exc:
            raise fail(exc) from exc
        flt.save(project_dir, data)
        return JSONResponse(payload())

    @app.post("/api/higgsfield/login")
    def higgsfield_login() -> JSONResponse:
        """Ricollega Higgsfield: si apre il login nel browser, poi l'editor ricontrolla."""
        try:
            ai.agent.start_login()
        except (AgentError, OSError) as exc:
            raise HTTPException(502, str(exc)) from exc
        return JSONResponse({"started": True})

    if keepalive:

        def keep_session() -> None:
            # La CLI rinnova da sola il token quando viene usata: un controllo ogni 20 minuti
            # tiene viva la sessione finché l'editor è acceso.
            while True:
                time.sleep(20 * 60)
                try:
                    ai.agent.status(refresh=True)
                except Exception:  # mai fermare l'editor per questo
                    pass

        threading.Thread(target=keep_session, daemon=True).start()

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

    @app.post("/api/popups/add")
    def popups_add(body: StickerBody) -> JSONResponse:
        """Sticker aggiunto a mano dal pannello Sticker: approvato, posizione libera."""
        if body.image is not None:
            path = (work_dir / body.image).resolve()
            if not path.is_relative_to(work_dir.resolve()) or not path.is_file():
                raise HTTPException(404, f"immagine {body.image} non trovata nel progetto")
        add = {
            **body.model_dump(exclude_none=True),
            "placement": "free",
            "status": "approved",
            "style": state().get("style"),
        }
        try:
            new, log = pops.apply_ops(popups_file(), {"add": [add]}, "user")
        except pops.PopupError as exc:
            raise fail(exc) from exc
        pops.save(project_dir, new)
        out = payload()
        out["added"] = log[-1].split()[-1] if log else None
        return JSONResponse(out)

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

    # --- immagini: cerca sul web, scarica, scontorna (solo su richiesta dell'utente) -----

    img_jobs: dict[str, dict[str, Any]] = {}
    img_ids = itertools.count(1)
    img_lock = threading.Lock()
    search_fn = image_search or imgs.search
    fetch_fn = image_fetch or imgs.fetch
    masker = image_masker or imgs.mask_for

    def run_image_job(job_id: str, body: ImageAddBody) -> None:
        job = img_jobs[job_id]
        name = None

        def progress(phase: str, frac: float | None) -> None:
            job.update(phase=phase, progress=frac)

        try:
            if body.redo:
                name = body.redo.rsplit("/", 1)[-1]
                raw = imgs.original(img_dir / name)
                info = imgs.prepare(
                    raw, img_dir / name, cutout=body.cutout, quality=body.quality,
                    progress=progress, masker=masker,
                )  # fmt: skip
                meta = imgs.library(work_dir)
                old = next((m for m in meta if m["image"] == body.redo), {})
                keep = {k: old.get(k) for k in ("title", "source", "page", "license")}
                imgs.remember(img_dir, name, {**keep, "cutout": info["cutout"],
                                               "quality": info["quality"]})  # fmt: skip
                job.update(status="done", phase="done", image=body.redo, **info)
                return
            if body.data:
                job.update(phase="reading")
                raw = base64.b64decode(body.data.split(",", 1)[-1])
                if len(raw) > imgs.MAX_BYTES:
                    raise imgs.ImageError("immagine troppo pesante (oltre 25 MB)")
            else:
                job.update(phase="downloading")
                raw = fetch_fn(body.url or "", referer=body.page, fallback=body.thumb)
            with img_lock:
                name = imgs.next_name(img_dir)
                img_dir.mkdir(parents=True, exist_ok=True)
                (img_dir / name).write_bytes(b"")  # prenota il nome
            info = imgs.prepare(
                raw, img_dir / name, cutout=body.cutout, quality=body.quality,
                progress=progress, masker=masker,
            )  # fmt: skip
            imgs.remember(img_dir, name, {
                "title": body.title[:120], "source": body.source, "page": body.page,
                "license": body.license, "cutout": info["cutout"], "quality": info["quality"],
            })  # fmt: skip
            job.update(
                status="done", phase="done", image=f"{imgs.IMAGES_DIR}/{name}",
                url=f"/media/images/{name}", **info,
            )  # fmt: skip
        except Exception as exc:  # qualsiasi errore va mostrato nel pannello
            if name and (img_dir / name).is_file() and (img_dir / name).stat().st_size == 0:
                (img_dir / name).unlink(missing_ok=True)
            job.update(status="error", error=str(exc) or exc.__class__.__name__)

    @app.get("/api/images/search")
    def images_search(q: str, transparent: bool = False, free: bool = False) -> JSONResponse:
        if not q.strip():
            raise HTTPException(400, "scrivi cosa cercare")
        try:
            results = search_fn(q, transparent=transparent, free=free)
        except imgs.ImageError as exc:
            raise HTTPException(502, str(exc)) from exc
        return JSONResponse({"query": imgs.clean_query(q), "results": results})

    @app.post("/api/images/add")
    def images_add(body: ImageAddBody) -> JSONResponse:
        """Scarica (o legge dal PC) e scontorna: lavoro in background, il pannello lo segue."""
        if not body.data and not body.url and not body.redo:
            raise HTTPException(400, "manca l'immagine")
        if body.quality not in imgs.QUALITIES:
            raise HTTPException(400, f"qualità {body.quality!r} sconosciuta")
        if body.redo and not (img_dir / body.redo.rsplit("/", 1)[-1]).is_file():
            raise HTTPException(404, f"immagine {body.redo} non trovata")
        job_id = f"img{next(img_ids)}"
        img_jobs[job_id] = {"id": job_id, "status": "running", "phase": "queued", "progress": None}
        if image_runner:
            image_runner(run_image_job, job_id, body)
        else:
            threading.Thread(target=run_image_job, args=(job_id, body), daemon=True).start()
        return JSONResponse(img_jobs[job_id])

    @app.get("/api/images/job/{job_id}")
    def images_job(job_id: str) -> JSONResponse:
        job = img_jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "lavoro non trovato")
        return JSONResponse(job)

    @app.get("/media/images/{name}")
    def image_file(name: str) -> FileResponse:
        base = img_dir.resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.suffix != ".png":
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

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
