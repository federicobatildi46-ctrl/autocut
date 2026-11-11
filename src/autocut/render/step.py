"""Comando `autocut style-preview`: brand × stile su pochi secondi del video vero."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import audio_mix, effects, filters, manual_cuts, music, text_style
from ..brands import list_brands
from ..ingest.fingerprint import fingerprint
from ..models.io import read_model
from ..models.timeline import Timeline
from ..overrides import store
from ..overrides.resolve import effective_ranges
from ..paths import TIMELINE_FILE, project_dir
from ..styles import list_styles, resolve_look
from .preview import (
    RenderError,
    _catalog,
    build_props,
    ensure_masks,
    ensure_source,
    run_remotion,
    sfx_loudness,
    stage_sounds,
    to_out,
    voice_gain_db,
)

STATE_FILE = "editor_state.json"


@dataclass(frozen=True)
class PreviewResult:
    output: Path
    style: str
    brand: str | None
    frame: int | None
    duration_ms: int
    sounds: int


def run_style_preview(
    name: str,
    *,
    style_id: str | None,
    brand_id: str | None,
    at_ms: int,
    before_ms: int = 2000,
    after_ms: int = 2000,
    hook: str | None = None,
    clip: bool = False,
    projects_root: Path | None = None,
    styles_root: Path | None = None,
    brands_root: Path | None = None,
    log: Callable[[str], None] = lambda s: None,
) -> PreviewResult:
    pdir = project_dir(name, None, projects_root)
    tl_path = pdir / TIMELINE_FILE
    if not tl_path.exists():
        raise RenderError(f"nessuna timeline in {pdir}: lancia prima ingest, transcribe e cuts")
    tl = read_model(tl_path, Timeline)
    state_path = pdir / STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    styles = {s.id: s for s in list_styles(styles_root)}
    sid = style_id or state.get("style")
    if sid not in styles:
        raise RenderError(
            f"stile {sid!r} non trovato (disponibili: {', '.join(styles) or 'nessuno'})"
        )
    brands = {b.id: b for b in list_brands(brands_root)}
    bid = brand_id if brand_id is not None else state.get("brand")
    if bid and bid not in brands:
        raise RenderError(f"brand {bid!r} non trovato in brands/")
    brand = brands.get(bid) if bid else None
    style = styles[sid]
    v = tl.sources.camera.video
    look = resolve_look(style, brand, portrait=v.display_height >= v.display_width)
    text = text_style.for_style(text_style.load(pdir), sid)  # scelte del pannello Testo
    look = text_style.apply_to_look(look, text)
    # colore del pannello Filtri
    look = filters.apply_to_look(look, filters.for_style(filters.load(pdir), sid))

    cam = tl.sources.camera
    src = Path(cam.path_hint) if cam.path_hint else None
    if src is None or not src.is_file():
        raise RenderError(f"file camera non trovato: {cam.path_hint} (rilancia ingest)")
    if fingerprint(src) != cam.fingerprint:
        raise RenderError(f"{cam.file_name} è cambiato dall'ingest: rilancia ingest")

    start = max(0, at_ms - before_ms)
    end = min(cam.duration_ms, at_ms + after_ms)
    ov = store.load(pdir, tl)
    ov, _, _ = store.reconcile(ov, tl)
    eff = manual_cuts.apply(effective_ranges(tl, ov), manual_cuts.load(pdir))  # + tagli a mano

    work = pdir / "work"
    # effetti del pannello Effetti e punti di transizione (tagli / cambi di scena)
    fx_res = effects.resolved(sid, effects.for_style(effects.load(pdir), sid))
    proxy = next(iter(sorted(work.glob("proxy-*.mp4"))), None)
    rng = tl.run.range
    fx_points = effects.boundaries(
        tl, eff, video=proxy, offset_ms=rng.start_ms if rng else 0, cache_path=work / "scenes.json"
    )
    # suoni e volumi del pannello Audio: stesso piano dell'editor, calcolato su tutto il video
    hook_text = hook if hook is not None else state.get("hook")
    mix = audio_mix.for_style(audio_mix.load(pdir), sid)
    catalog = _catalog()
    plan = audio_mix.auto_plan(
        end_ms=max((r.end_ms for r in eff), default=0), project_dir=pdir, tl=tl, eff=eff,
        look=look, hook_text=hook_text, catalog=catalog, loudness=sfx_loudness,
        scenes=text.scenes, effects=fx_res, points=fx_points,
    )  # fmt: skip
    sounds_raw = audio_mix.resolve(plan, mix, look, catalog, sfx_loudness)
    gain = voice_gain_db(work, tl, src, look["sound"]["voice_lufs"])
    gain = round(gain + audio_mix.voice_offset_db(mix), 1)
    span = f"{start / 1000:.1f}-{end / 1000:.1f} s"
    log(f"estratto {span} dal raw (solo lettura), voce {gain:+.1f} dB...")
    source = ensure_source(work, tl, src, start, end, gain_db=gain)
    from .. import vfx  # clip AI di «Genera con Higgsfield» attive: cucite dentro l'estratto

    if vfx.active(pdir):
        log("clip AI (Genera con Higgsfield) dentro il video...")
        source = vfx.bake(pdir, source, start, end)
    from .. import broll  # B-roll (foto e video di supporto) e voice-over caricati dal creator

    if broll.active_clips(pdir):
        log("B-roll sopra il parlato...")
        source = broll.bake(pdir, source, start, end)
    props, pieces = build_props(
        project_dir=pdir,
        tl=tl,
        eff=eff,
        look=look,
        window=(start, end),
        source_rel=source.relative_to(work).as_posix(),
        hook_text=hook_text,
        loudness=sfx_loudness,
        scenes=text.scenes,
        effects=fx_res,
        points=fx_points,
        sounds_raw=sounds_raw,
    )
    stage_sounds(props["sounds"], work)
    props["voiceovers"] = broll.render_voices(pdir, work, to_out, pieces)
    props["music"] = music.render_music(pdir, work, to_out, pieces, sid, look["sound"])
    for m in props["music"]:
        log(f"  musica {m['from_ms'] / 1000:5.2f} s per {m['dur_ms'] / 1000:.1f} s  {m['id']}")
    for vo in props["voiceovers"]:
        log(f"  voice-over {vo['from_ms'] / 1000:5.2f} s  {vo['id']}")
    if any(c.get("layer") == "person" for c in props["cards"]):
        log("sagoma della persona per le grafiche dietro (MediaPipe, in locale)...")
        masks, count = ensure_masks(source)
        props["video"]["masks"] = {"dir": masks.relative_to(work).as_posix(), "count": count}
    for s in props["sounds"]:
        at = s["event_ms"] / 1000
        log(f"  suono {at:5.2f} s  {s['type']:<24} {s['gain_db']:+.1f} dB  {s['reason']}")

    tag = f"{sid}{'-' + bid if bid else ''}-{at_ms // 100 / 10:g}s"
    renders = pdir / "renders"
    frame = None
    if clip:
        out = renders / f"style-{tag}.mp4"
        log(f"render della clip con Remotion ({props['durationInFrames']} fotogrammi)...")
    else:
        at_out = to_out(pieces, at_ms)
        if at_out is None:  # l'istante cade in un taglio: prende il primo tratto dopo
            at_out = next(
                (p.out_start for p in pieces if p.src_start >= at_ms), pieces[-1].out_start
            )
        frame = min(props["durationInFrames"] - 1, round(at_out / 1000 * props["fps"]))
        out = renders / f"style-{tag}.png"
        log(f"fotogramma {frame} con Remotion...")
    run_remotion(props, work / "render" / f"props-{tag}.json", out, work, frame=frame)
    return PreviewResult(
        output=out,
        style=sid,
        brand=bid,
        frame=frame,
        duration_ms=round(props["durationInFrames"] / props["fps"] * 1000),
        sounds=len(props["sounds"]),
    )
