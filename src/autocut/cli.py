"""CLI di autocut: ingest, transcribe, cuts, editor. In arrivo: sync, repeats, raw."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from .cuts.step import CutsError, run_cuts
from .editor.launch import EditorError
from .editor.media import MediaError
from .env import API_KEY_VAR, api_key
from .ingest.classify import AmbiguousClassification
from .ingest.probe import ProbeError
from .ingest.step import IngestError, run_ingest
from .models.export import write_schemas
from .paths import ProjectNameError
from .settings import SettingsError
from .timeparse import RangeError
from .transcribe.audio import AudioExtractError
from .transcribe.scribe import ScribeError
from .transcribe.step import TranscribeError, run_transcribe

EXIT_ERROR = 1
EXIT_AMBIGUOUS = 2

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Motore di montaggio automatico."
)


@app.command()
def doctor() -> None:
    """Verifica ffmpeg, ffprobe e la API key di ElevenLabs."""
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        typer.echo(f"{tool:8} {'OK    ' + path if path else 'MANCA'}")
        ok = ok and bool(path)
    has_key = api_key() is not None
    typer.echo(f"{API_KEY_VAR} {'OK' if has_key else 'MANCA (env o .env)'}")
    ok = ok and has_key
    raise typer.Exit(0 if ok else 1)


CameraOpt = Annotated[
    str | None, typer.Option("--camera", help="File camera (da solo = nessuno schermo).")
]
ScreenOpt = Annotated[
    str | None, typer.Option("--screen", help="File schermo (richiede --camera).")
]
ProfileOpt = Annotated[
    str | None, typer.Option("--profile", help="long | short (default: dall'orientamento).")
]
RangeOpt = Annotated[
    str | None, typer.Option("--range", help="Solo un tratto, es. 60-180 o 1:00-3:00.")
]
SetOpt = Annotated[
    list[str] | None, typer.Option("--set", help="Sovrascrive un'impostazione: chiave=valore.")
]


@app.command()
def ingest(
    name: Annotated[str, typer.Argument(help="Nome del progetto.")],
    folder: Annotated[Path, typer.Argument(help="Cartella con i file raw.")],
    camera: CameraOpt = None,
    screen: ScreenOpt = None,
    profile: ProfileOpt = None,
    range_: RangeOpt = None,
    set_: SetOpt = None,
) -> None:
    """Riconosce camera e schermo e scrive la prima timeline del progetto."""
    try:
        result = run_ingest(
            name,
            folder,
            camera=camera,
            screen=screen,
            profile=profile,
            sets=set_ or (),
            range_text=range_,
        )
    except AmbiguousClassification as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_AMBIGUOUS) from None
    except (IngestError, ProbeError, SettingsError, RangeError, ProjectNameError) as exc:
        typer.echo(f"errore: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None

    tl = result.timeline
    cam = tl.sources.camera
    typer.echo(
        f"camera  {cam.file_name}  {cam.video.display_width}x{cam.video.display_height} "
        f"{cam.video.orientation} {cam.video.fps} fps  {cam.duration_ms / 1000:.1f} s"
    )
    if tl.sources.screen:
        scr = tl.sources.screen
        typer.echo(
            f"schermo {scr.file_name}  {scr.video.display_width}x{scr.video.display_height} "
            f"{scr.duration_ms / 1000:.1f} s  (audio solo per la sync)"
        )
    else:
        typer.echo("schermo nessuno")
    typer.echo(f"profilo {tl.settings.profile} ({tl.settings.profile_source})")
    for ignored in tl.detection.ignored:
        typer.echo(f"ignorato {ignored}")
    for w in tl.warnings:
        typer.echo(f"avviso  {w.message}")
    typer.echo(f"scritto {result.timeline_path}")


@app.command()
def transcribe(
    name: Annotated[str, typer.Argument(help="Nome del progetto.")],
    range_: RangeOpt = None,
    force: Annotated[
        bool, typer.Option("--force", help="Rifà la trascrizione anche se è in cache.")
    ] = False,
) -> None:
    """Trascrive l'audio della camera con ElevenLabs Scribe (con cache)."""

    def announce(seconds: float) -> None:
        typer.echo(f"invio {seconds:.1f} s di audio a ElevenLabs Scribe...")

    try:
        result = run_transcribe(name, range_text=range_, force=force, on_upload=announce)
    except (
        TranscribeError,
        ScribeError,
        AudioExtractError,
        RangeError,
        ProjectNameError,
    ) as exc:
        typer.echo(f"errore: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None

    tl = result.timeline
    words = [w for w in tl.words if w.kind == "word"]
    events = [w for w in tl.words if w.kind == "audio_event"]
    t = tl.transcript
    lang = f"{t.language_code} (p={t.language_probability})" if t and t.language_code else "?"
    typer.echo(
        f"{'dalla cache' if result.from_cache else 'trascritto'}: {len(words)} parole, "
        f"{len(events)} eventi audio, lingua {lang}"
    )
    preview = " ".join(w.text for w in tl.words)
    typer.echo(f"testo   {preview[:300]}{'...' if len(preview) > 300 else ''}")
    typer.echo(f"cache   {result.cache_path}")
    typer.echo(f"scritto {result.timeline_path}")


def _clock(ms: int) -> str:
    return f"{ms // 60000}:{(ms % 60000) / 1000:05.2f}"


@app.command()
def cuts(
    name: Annotated[str, typer.Argument(help="Nome del progetto.")],
    range_: RangeOpt = None,
    set_: SetOpt = None,
) -> None:
    """Toglie le pause morte: scrive i segmenti tenuti/tolti nella timeline."""
    try:
        result = run_cuts(name, range_text=range_, sets=set_ or ())
    except (CutsError, SettingsError, RangeError, ProjectNameError) as exc:
        typer.echo(f"errore: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None

    tl = result.timeline
    p = tl.settings.pauses
    typer.echo(
        f"profilo {tl.settings.profile}: soglia {p.threshold_ms} ms, margine {p.margin_ms} ms"
    )
    for seg in tl.segments:
        if seg.state == "remove":
            typer.echo(
                f"  tolto {_clock(seg.start_ms)} -> {_clock(seg.end_ms)}  "
                f"({(seg.end_ms - seg.start_ms) / 1000:.2f} s)  {seg.reason}"
            )
    st = tl.stats
    if st:
        typer.echo(
            f"raw {st.raw_ms / 1000:.2f} s -> tenuti {st.kept_ms / 1000:.2f} s, "
            f"tolti {st.removed_ms / 1000:.2f} s ({100 * st.removed_ms / st.raw_ms:.0f}%)"
        )
    for target in result.orphaned:
        typer.echo(f"orfano  la tua scelta su {target} non ha più una proposta: non è applicata")
    for target in result.restored:
        typer.echo(f"ripreso la tua scelta su {target} torna valida")
    typer.echo(f"scritto {result.timeline_path}")


@app.command()
def editor(
    name: Annotated[str, typer.Argument(help="Nome del progetto.")],
    range_: RangeOpt = None,
    port: Annotated[int, typer.Option("--port", help="Porta locale.")] = 8765,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Non aprire il browser.")
    ] = False,
) -> None:
    """Apre l'editor visivo in locale (http://127.0.0.1:<porta>)."""
    from .editor.launch import build, serve

    try:
        app_, pdir = build(name, range_text=range_, log=lambda s: typer.echo(f"preparo {s}"))
    except (EditorError, MediaError, RangeError, ProjectNameError) as exc:
        typer.echo(f"errore: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    typer.echo(f"editor di {pdir.name} su http://127.0.0.1:{port}/  (Ctrl+C per chiudere)")
    serve(app_, port=port, open_browser=not no_browser)


@app.command("export-schemas")
def export_schemas(
    out: Annotated[
        Path | None, typer.Option(help="Cartella di destinazione (default: schemas/).")
    ] = None,
) -> None:
    """Rigenera i JSON Schema di timeline.json e overrides.json dai modelli."""
    for path in write_schemas(out):
        typer.echo(f"scritto {path}")


if __name__ == "__main__":
    app()
