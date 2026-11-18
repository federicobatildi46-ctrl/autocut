"""Copertine (miniature) del video: Shorts 9:16 e YouTube 16:9, prima dell'esportazione.

Stile Viral: solo la copertina verticale, fatta in locale e gratis (niente Higgsfield): un
fotogramma del video + la frase d'esordio al centro, con font, contorno e ombra dell'hook del
video, al massimo due emoji stile iPhone (render Remotion, composizione ViralCover).

Stile Premium:

- Claude propone la frase (piccola sopra, grande sotto) e la scena di sfondo dal parlato;
  l'utente le corregge nella finestra Esporta.
- Higgsfield le genera solo quando l'utente preme Genera (costano crediti): prima Soul 2 con il
  personaggio allenato (volto fedele, luce da copertina), poi GPT Image 2 in 4K impagina scritta,
  sfondo e luce partendo da quella foto e dalla foto del volto.
- Tutto in projects/<nome>/covers.json e work/covers/ (fuori da git). Per ogni formato si tengono
  tutte le versioni; quella scelta è la copertina dell'export.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

COVERS_FILE = "covers.json"
COVERS_DIR = "covers"  # dentro work/
RATIOS = ("9:16", "16:9")
SOUL_MODEL = "text2image_soul_v2"  # Soul 2.0 nella CLI; il personaggio va in custom_reference_id
COVER_MODEL = "gpt_image_2"  # impaginazione finale: scritte affidabili, 4K
COST_HINT = "circa 11 crediti per copertina"


class Concept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(default="", max_length=400)  # di cosa parla il video (per Claude)
    kicker: str = Field(default="", max_length=40)  # riga piccola sopra
    title: str = Field(default="", max_length=28)  # parola/riga grande
    scene: str = Field(default="", max_length=600)  # sfondo, in inglese per il modello
    expression: str = Field(default="calm, confident, quietly excited half-smile", max_length=200)
    wardrobe: str = Field(default="", max_length=200)
    sub: str = Field(default="", max_length=40)  # Viral: riga piccolissima sotto (es. «a scuola»)
    emojis: str = Field(default="", max_length=16)  # Viral: 0-2 emoji ai lati della prima riga
    frame_ms: int | None = Field(default=None, ge=0)  # Viral: fotogramma del video (ms del raw)
    accent: str | None = Field(
        default=None, pattern=r"^#[0-9A-Fa-f]{6}$"
    )  # Viral: colore riga piccola
    font: str | None = Field(
        default=None, max_length=60
    )  # Viral: font (default: quello dell'apertura)


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str  # nome in work/covers/
    job_id: str | None = None
    title: str = ""
    at: str = ""


class StyleCovers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: Concept = Field(default_factory=Concept)
    versions: dict[str, list[Version]] = Field(default_factory=dict)  # per formato
    chosen: dict[str, int] = Field(default_factory=dict)  # indice della versione scelta


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    soul_id: str | None = None  # personaggio Soul 2 su Higgsfield
    face: str | None = None  # foto del volto in work/covers/


class CoversFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    person: Person = Field(default_factory=Person)
    styles: dict[str, StyleCovers] = Field(default_factory=dict)


class CoverError(RuntimeError):
    pass


def load(project_dir: Path) -> CoversFile:
    p = project_dir / COVERS_FILE
    if not p.exists():
        return CoversFile()
    try:
        return CoversFile.model_validate_json(p.read_bytes())
    except ValidationError as exc:
        raise CoverError(f"{p}: {exc}") from exc


def save(project_dir: Path, data: CoversFile) -> None:
    p = project_dir / COVERS_FILE
    tmp = p.with_suffix(".partial")
    body = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def for_style(data: CoversFile, style: str | None) -> StyleCovers:
    return data.styles.get(style or "", StyleCovers())


def with_style(data: CoversFile, style: str | None, sc: StyleCovers) -> CoversFile:
    return data.model_copy(update={"styles": {**data.styles, style or "": sc}})


def add_version(data: CoversFile, style: str | None, ratio: str, v: Version) -> CoversFile:
    sc = for_style(data, style)
    lst = [*sc.versions.get(ratio, []), v]
    sc = sc.model_copy(update={"versions": {**sc.versions, ratio: lst},
                               "chosen": {**sc.chosen, ratio: len(lst) - 1}})  # fmt: skip
    return with_style(data, style, sc)


def choose(data: CoversFile, style: str | None, ratio: str, index: int) -> CoversFile:
    sc = for_style(data, style)
    if not 0 <= index < len(sc.versions.get(ratio, [])):
        raise CoverError("versione non trovata")
    return with_style(data, style, sc.model_copy(update={"chosen": {**sc.chosen, ratio: index}}))


def ratio_slug(ratio: str) -> str:
    return ratio.replace(":", "x")


def next_file(folder: Path, style: str | None, ratio: str) -> str:
    stem = f"{style or 'base'}-{ratio_slug(ratio)}-"
    nums = [
        int(m.group(1))
        for p in (folder.glob(f"{stem}*.png") if folder.is_dir() else [])
        if (m := re.fullmatch(re.escape(stem) + r"(\d+)\.png", p.name))
    ]
    return f"{stem}{(max(nums) + 1 if nums else 1)}.png"


# --- Claude: frase e scena ---------------------------------------------------------------


def concept_prompt(style_name: str, words: str, hint: str) -> str:
    return f"""Sei il grafico delle copertine YouTube di un creator italiano. Stile: «{style_name}».
Proponi la copertina del video (vale sia per lo Shorts 9:16 sia per il video orizzontale 16:9).

Di cosa parla il video secondo il creator (vince su tutto): {hint or "(non indicato)"}
Inizio del parlato: {words[:2500]}

Regole:
- una promessa vera del video, niente numeri o fatti inventati;
- "kicker": riga piccola sopra, 2-4 parole MAIUSCOLE (es. «ME NE VADO IN»);
- "title": la parola o riga grande, 1-2 parole MAIUSCOLE, massimo 14 caratteri (es. «THAILANDIA»);
- "scene": lo sfondo in INGLESE, un luogo reale e riconoscibile legato al tema, ora del giorno,
  luce e 2-3 elementi tipici (es. "Krabi, Thailand at golden hour — limestone karst cliffs,
  turquoise water, a wooden longtail boat"); niente persone in più, niente scritte;
- "expression": l'espressione del creator in INGLESE (credibile, mai esagerata nello stile premium);
- "wardrobe": vestiti in INGLESE adatti al luogo;
- "topic": una frase in italiano su di cosa parla il video.

Rispondi SOLO con JSON: {{"topic": "...", "kicker": "...", "title": "...", "scene": "...",
"expression": "...", "wardrobe": "..."}}"""


def clean_concept(raw: dict[str, Any], current: Concept, *, allow_empty: bool = False) -> Concept:
    """allow_empty: dal pannello un campo vuoto si svuota; da Claude un campo vuoto si ignora."""
    fields: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in Concept.model_fields:
            continue
        if k == "frame_ms":
            fields[k] = None if v in (None, "") else int(v)
        elif k in ("accent", "font"):
            fields[k] = str(v).strip() or None if v is not None else None
        elif v or (allow_empty and v is not None):
            fields[k] = str(v).strip()
    for k in ("kicker", "title"):
        if k in fields:
            fields[k] = fields[k].upper()[: Concept.model_fields[k].metadata[0].max_length]
    try:
        return Concept.model_validate({**current.model_dump(), **fields})
    except ValidationError as exc:
        raise CoverError(f"proposta di Claude non valida: {exc.errors()[0]['msg']}") from exc


def viral_concept_prompt(words: str, hint: str) -> str:
    return f"""Sei l'editor di un creator italiano di short virali (stile provinciale, ironico,
diretto, come le pagine che fanno milioni di views). Scrivi la FRASE D'ESORDIO della copertina
verticale: quella che si legge nei primi 3 secondi e fa fermare il pollice.

Di cosa parla il video secondo il creator (vince su tutto): {hint or "(non indicato)"}
Inizio del parlato: {words[:2000]}

Regole (guarda gli esempi «PER TUTTI ERO / "IL CINESE" / a scuola» e «A STO GIRO L'AVETE /
FATTA GROSSA / arrivo al locale»):
- "kicker": riga piccola sopra, 2-5 parole, parlata, crea curiosità;
- "title": la riga grande, 1-3 parole che si leggono in un attimo (anche tra virgolette «"»),
  massimo 20 caratteri;
- "sub": riga minuscola sotto, 1-3 parole di contesto in minuscolo (può essere vuota);
- "emojis": 0-2 emoji che rafforzano l'emozione (es. "🤬⚠️", "😱", "🇹🇭✈️"), niente di più;
- italiano naturale, niente clickbait falso: deve essere vero rispetto al video;
- NON inventare età, numeri, cifre, nomi, luoghi o fatti che non sono nel parlato o nella frase
  del creator (niente «A 25 ANNI…» se l'età non è detta);
- "topic": una frase su di cosa parla il video.
Rispondi SOLO con JSON: {{"kicker": "...", "title": "...", "sub": "...", "emojis": "...", "topic": "..."}}"""


def render_viral(
    project_dir: Path,
    tl: Any,
    look: dict[str, Any],
    c: Concept,
    frame_ms: int,
    dest: Path,
    *,
    still: Callable[..., Path] | None = None,
    grab: Callable[[Path, int, Path], Path] | None = None,
) -> Path:
    """Copertina Viral 9:16: fotogramma del raw (solo lettura) + frase d'esordio + emoji."""
    from .render.preview import RenderError, _stage_emoji, ensure_source, hook_lines, run_remotion

    project_dir = project_dir.resolve()  # Remotion lavora da motion/: percorsi assoluti
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not c.title:
        raise CoverError("manca la riga grande della frase d'esordio")
    work = project_dir / "work"
    cam = tl.sources.camera
    src = Path(cam.path_hint) if cam.path_hint else None
    frame_rel = f"render/cover-frame-{frame_ms}.jpg"
    frame_path = work / frame_rel
    video_rel = None
    if grab is None:
        # come il video: un pezzetto H.264 preparato come nel render, letto da Remotion con lo
        # stesso look colore (dal file HDR dell'iPhone un fotogramma "grezzo" esce spento)
        if src is None or not src.is_file():
            raise CoverError(f"file del video non trovato: {cam.path_hint}")
        try:
            clip = ensure_source(work, tl, src, frame_ms, frame_ms + 400)
        except RenderError as exc:
            raise CoverError(str(exc)) from exc
        video_rel = clip.relative_to(work).as_posix()
    elif not frame_path.exists():
        grab(src or Path(), frame_ms, frame_path)
    text = "|".join(x for x in (c.kicker, f"*{c.title}*", c.sub) if x)
    hook = {**VIRAL_HOOK, **{k: v for k, v in (look.get("hook") or {}).items() if k in VIRAL_HOOK}}
    if c.font:
        hook.update(font=c.font, big_font=c.font)
    props = {
        "width": 1080,
        "height": 1920,
        "frame": frame_rel,
        "video": video_rel,
        "fonts_url": look.get("fonts_url"),
        "hook": hook,
        "accent": c.accent or auto_accent(look),
        "lines": hook_lines(text),
        "emojis": (_stage_emoji(project_dir, c.emojis) or [])[:2] if c.emojis else [],
        "grade": (look.get("grade") or {}).get("css_filter") or "",
    }
    try:
        (still or run_remotion)(
            props, work / "render" / "props-cover.json", dest, work, frame=0,
            composition="ViralCover",
        )  # fmt: skip
    except RenderError as exc:
        raise CoverError(str(exc)) from exc
    return dest


def _luma(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def auto_accent(look: dict[str, Any]) -> str:
    """Colore della riga piccola: l'evidenziazione del video se si legge bene, se no quella del
    brand, se no arancione (come i reference)."""
    emph = ((look.get("captions") or {}).get("emphasis") or {}).get("color")
    for color in (emph, (look.get("brand_palette") or {}).get("highlight"), "#FFB800"):
        if color and re.fullmatch(r"#[0-9A-Fa-f]{6}", color) and _luma(color) >= 0.45:
            return color
    return "#FFB800"


# hook del video quando lo stile non lo definisce (stessi valori del preset viral)
VIRAL_HOOK = {
    "center_pct": 63.0, "size_pct": 12.5, "kicker_ratio": 0.58, "sub_ratio": 0.42,
    "font": "Lilita One", "big_font": "Lilita One", "weight": 400, "big_weight": 400,
    "big_italic": False, "case": "upper", "stroke_px": 7.0, "stroke_color": "#000000",
    "big_stroke_color": "#000000", "shadow": "hard",
}  # fmt: skip


def grab_frame(src: Path, ms: int, dest: Path) -> Path:
    """Un fotogramma del raw a 1080x1920 (riempie e taglia ai lati se serve). Il raw si legge."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CoverError("ffmpeg non trovato")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".partial.jpg")
    proc = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-nostdin", "-y", "-ss", f"{ms / 1000:.3f}", "-i", str(src),
         "-frames:v", "1", "-vf",
         "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920",
         "-q:v", "2", str(tmp)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if proc.returncode != 0 or not tmp.exists():
        raise CoverError(f"fotogramma non estratto: {(proc.stderr or '').strip()[-200:]}")
    tmp.replace(dest)
    return dest


def attach_cover(video: Path, cover: Path | None, dest: Path) -> Path:
    """Copia il video in dest con la copertina dentro (miniatura del file, ffmpeg senza
    ricodificare). Se qualcosa va storto resta il video senza copertina."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if cover is not None and cover.is_file() and ffmpeg:
        tmp = dest.with_name(dest.stem + ".partial.mp4")
        proc = subprocess.run(
            [ffmpeg, "-loglevel", "error", "-nostdin", "-y", "-i", str(video), "-i", str(cover),
             "-map", "0", "-map", "1", "-c", "copy", "-c:v:1", "png",
             "-disposition:v:1", "attached_pic", str(tmp)],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        if proc.returncode == 0 and tmp.exists():
            tmp.replace(dest)
            return dest
        tmp.unlink(missing_ok=True)
    shutil.copy2(video, dest)
    return dest


def default_frame_ms(eff: list[Any]) -> int:
    """Apertura del video: poco dopo l'inizio del primo pezzo tenuto (i primi 3 secondi)."""
    keep = [r for r in eff if r.state == "keep"]
    if not keep:
        return 0
    r = keep[0]
    return min(r.end_ms - 1, r.start_ms + 700)


# --- prompt per Higgsfield ---------------------------------------------------------------

LIGHT = ("signature YouTube thumbnail lighting rig — strong soft key light sculpting the face, soft "
         "dreamy fill lifting the shadows, defined warm golden back light and hair light tracing a "
         "clean bright rim around hair, shoulders and silhouette.")  # fmt: skip
GRADE_PREMIUM = ("premium and refined — warm skin tones, rich colors, deep clean shadows, crisp "
                 "highlights, glossy but not oversaturated, cohesive as one image.")  # fmt: skip


def base_prompt(c: Concept, ratio: str) -> str:
    """Soul 2: la persona nel luogo, con la luce giusta e lo spazio per la scritta."""
    where = ("centered, face in the upper half, lots of clean sky above the head for a title"
             if ratio == "9:16" else
             "on the right third, large in frame, clean open sky on the left for a title")  # fmt: skip
    return (
        f"Premium travel-magazine portrait, {'vertical' if ratio == '9:16' else 'horizontal wide'}"
        f" frame. The man stands chest-up {where}, looking straight into the camera. Expression: "
        f"{c.expression}. He wears his own glasses if he has them"
        f"{', ' + c.wardrobe if c.wardrobe else ''}. Background: {c.scene}. Lighting: {LIGHT} "
        "Shallow depth of field, background softly blurred but recognizable, face crisp and "
        "sharp. Photoreal, high-end, no text."
    )


def cover_prompt(c: Concept, ratio: str, *, has_face: bool, has_base: bool) -> str:
    refs = []
    if has_face:
        refs.append(f"image {len(refs) + 1} = CHARACTER 1 face reference (identity)")
    if has_base:
        refs.append(f"image {len(refs) + 1} = scene, pose and wardrobe reference of the same "
                    "person (ignore any text in it)")  # fmt: skip
    head = f"IMAGE REFERENCES: {'; '.join(refs)}.\n\n" if refs else ""
    vertical = ratio == "9:16"
    kicker = (
        f'Line 1, small: "{c.kicker}" in clean white uppercase wide-tracked sans-serif with a thin gold rule. '
        if c.kicker
        else ""
    )  # noqa: E501
    big = f'"{c.title}" in ultra-bold condensed sans-serif, warm off-white letters with a subtle soft shadow'  # noqa: E501
    if vertical:
        text = (f"TEXT: baked into the image near the top, nothing else. {kicker}"
                f"Directly below, massive across the full width of the upper third: {big}. "
                "The top of the man's head may slightly overlap the bottom of the big word for a "
                "layered magazine-cover depth, while every letter stays readable.")  # fmt: skip
        place = ("He is centered, chest-up, filling about 50% of the frame, face in the upper "
                 "two-thirds.")  # fmt: skip
    else:
        text = (f"TEXT: baked into the image on the LEFT half, nothing else. {kicker}"
                f"Directly below, massive, filling most of the left half: {big}. Text never "
                "covers the face.")  # fmt: skip
        place = "He is on the RIGHT third, chest-up, large and foreground-dominant."
    spell = " / ".join(x for x in (c.kicker, c.title) if x)
    identity = (
        "CHARACTER 1: the person from attached face reference #1 — IDENTITY LOCK: reproduce this "
        "exact person with a photographic identity match — same bone structure, eye shape, nose, "
        "lips, jawline, facial hair, skin tone, hairline and hair, and the same glasses if any. "
        "Do not beautify, average or restyle the face. "
        if has_face else "CHARACTER 1: the man from the reference photo, same identity. "
    )  # fmt: skip
    return (
        f"{head}Premium YouTube {'Shorts cover, 9:16 vertical' if vertical else 'thumbnail, 16:9 horizontal'}, "  # noqa: E501
        "poster-grade and photoreal, high-impact but elegant like a luxury magazine cover. Single "
        "unified frame, no split-screen, no diagonal divide, everything blends organically.\n\n"
        f"SCENE: {c.scene}\n\n{text} Spell exactly: {spell}. No other text, no logos, no "
        "watermark.\n\n"
        f"{identity}Expression: {c.expression}, looking straight into the camera."
        f"{' Wardrobe: ' + c.wardrobe + '.' if c.wardrobe else ''} {place} All faces crisply "
        "sharp as the anchors of the shot.\n\n"
        "COMPOSITION: one clear hero, strong subject/background separation, background softly "
        "out of focus but recognizable, soft vignette and edge falloff.\n\n"
        f"LIGHTING: {LIGHT}\n\nGRADE: {GRADE_PREMIUM}"
    )


# --- generazione con la CLI Higgsfield ---------------------------------------------------

Runner = Callable[[list[str], str | None], dict[str, Any]]


def cli_runner(args: list[str], prompt: str | None) -> dict[str, Any]:
    """`higgsfield generate create ... --wait --json` (prompt da stdin se c'è)."""
    exe = shutil.which("higgsfield")
    if exe is None:
        raise CoverError("CLI Higgsfield non trovata: npm i -g @higgsfield/cli")
    proc = subprocess.run(
        [exe, *args], input=prompt, capture_output=True, text=True, encoding="utf-8",
        timeout=900, check=False,
    )  # fmt: skip
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        msg = (proc.stderr or out).strip()
        if "expired" in msg.lower() or "not authenticated" in msg.lower():
            raise CoverError("Higgsfield: sessione scaduta. Nel terminale: higgsfield auth login")
        raise CoverError(f"Higgsfield: {msg[-300:]}")
    for start in (i for i, ch in enumerate(out) if ch in "{["):
        try:
            return json.loads(out[start:])
        except ValueError:
            continue
    # testo semplice (avanzamento dell'upload, ecc.): link e id del lavoro dal testo
    url = re.search(r"https://\S+?\.(?:png|jpe?g|webp)", out)
    job = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out)
    if url or job:
        return {"result_url": url.group(0) if url else None, "id": job.group(0) if job else None}
    raise CoverError(f"risposta di Higgsfield non leggibile: {out[-200:]}")


def _result(data: Any) -> tuple[str | None, str | None]:
    """(job id, url del risultato) da una risposta della CLI, qualunque sia la forma."""
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None, None
    job = data.get("id") or data.get("job_id")
    url = data.get("result_url") or data.get("url")
    for key in ("results", "jobs", "result", "outputs", "images", "items"):
        sub = data.get(key)
        if not url and sub:
            sj, su = _result(sub)
            job, url = job or sj, su
    return job, url


def generate(
    c: Concept,
    ratio: str,
    person: Person,
    face_path: Path | None,
    dest: Path,
    *,
    runner: Runner = cli_runner,
    download: Callable[[str, Path], None] | None = None,
    progress: Callable[[str], None] = lambda s: None,
) -> str | None:
    """Genera una copertina in dest; restituisce il job id della copertina."""
    if ratio not in RATIOS:
        raise CoverError(f"formato {ratio!r} non previsto")
    if not c.title:
        raise CoverError("manca la scritta grande della copertina")
    base_job = None
    if person.soul_id:
        progress("person")
        data = runner(
            ["generate", "create", SOUL_MODEL, "--prompt", base_prompt(c, ratio),
             "--custom_reference_id", person.soul_id, "--aspect_ratio", ratio, "--quality", "2k",
             "--wait", "--json"], None,
        )  # fmt: skip
        base_job, _ = _result(data)
    progress("cover")
    args = ["generate", "create", COVER_MODEL, "--aspect_ratio", ratio, "--resolution", "4k",
            "--quality", "high"]  # fmt: skip
    if face_path is not None and face_path.is_file():
        args += ["--image", str(face_path)]
    if base_job:
        args += ["--image", base_job]
    prompt = cover_prompt(
        c, ratio, has_face=face_path is not None and face_path.is_file(), has_base=bool(base_job)
    )
    data = runner([*args, "--prompt", prompt, "--wait", "--json"], None)
    job, url = _result(data)
    if not url:
        raise CoverError("Higgsfield non ha restituito l'immagine")
    progress("download")
    (download or _download)(url, dest)
    return job


def _download(url: str, dest: Path) -> None:
    import ssl

    import httpx
    import truststore

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(verify=ctx, timeout=120, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
