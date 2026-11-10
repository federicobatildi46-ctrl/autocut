"""Genera con Higgsfield: effetti AI dentro la ripresa vera (skill `higgsfield-vfx`).

Flusso di un "colpo" (shot), max 3 s:
1. clip vera dal raw (stesso estratto del render, 1080x1920 30 fps) + versione 720p da inviare;
2. Claude + skill higgsfield-vfx scrive il prompt video-to-video e decide riferimento/protezione;
3. riferimento facoltativo (Soul 2.0, 0,12 crediti);
4. Seedance 2.0 video-to-video, 480p, 4 s, audio spento (stima dei crediti prima, tetto MAX_CREDITS);
5. composito in locale: allineamento al fotogramma, colore, persona vera sopra (sagoma MediaPipe),
   dissolvenza in entrata/uscita -> final-N.mp4 + foglio prima/dopo;
6. Claude rivede il foglio (ok / retry con prompt corretto / fail).
Il render "cuce" i colpi attivi dentro l'estratto della camera (bake): il resto del montaggio non cambia.
La voce resta sempre quella originale: le clip AI non hanno audio.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

VFX_FILE = "vfx.json"
WORK_DIR = "vfx"
MAX_EFFECT_MS = 3000
GEN_MS = 4000  # Seedance vuole almeno 4 s: si manda 4 s e si usano i primi dur_ms
FPS = 30
MAX_CREDITS = 6.0  # fase MVP: tetto per singola generazione video
FADE_FRAMES = 6
REF_MODEL = "text2image_soul_v2"
# Higgsfield: volti e labiale reggono in 4K, a 1080p iniziano a deformarsi nei movimenti; a 480p
# Seedance ridisegna la persona -> lì serve la protezione (persona vera sopra).
QUALITIES: dict[str, dict[str, Any]] = {
    "draft": {"label": "Bozza 480p", "job": "seedance_2_0", "credits": 4,
              "args": ["--mode", "fast", "--resolution", "480p"]},
    "cheap": {"label": "Economica 480p", "job": "seedance_2_0_mini", "credits": 2,
              "args": ["--resolution", "480p"]},
    # API a consumo (chiave in .env, saldo in dollari): Seedance 2.5 Video Edit è una VERA
    # modifica ("le parti non nominate restano invariate"), durata presa dalla clip sorgente.
    # Costo: token = altezza x larghezza x (secondi in ingresso + generati) x 24 / 1024.
    "api720": {"label": "API Seedance 2.5 Edit 720p (~2,2 $)", "api": "bytedance/seedance-2.5/video-edit",
               "resolution": "720p", "usd_per_ktok": 0.01284, "credits": 0},
    "api1080": {"label": "API Seedance 2.5 Edit 1080p (~5,5 $)", "api": "bytedance/seedance-2.5/video-edit",
                "resolution": "1080p", "usd_per_ktok": 0.01404, "credits": 0},
    "hd720": {"label": "Migliore sul piano Starter: 720p + upscale 1080p", "job": "seedance_2_0",
              "credits": 12, "upscale": True, "args": ["--mode", "fast", "--resolution", "720p"]},
    "hd": {"label": "Finale 1080p (piano Pro/Ultimate)", "job": "seedance_2_0", "credits": 48,
           "args": ["--mode", "std", "--resolution", "1080p"]},
    "uhd": {"label": "Finale 4K (piano Pro/Ultimate, consigliata)", "job": "seedance_2_0", "credits": 88,
            "args": ["--mode", "std", "--resolution", "4k"]},
}  # fmt: skip
# fedeltà della persona AI rispetto alla vera (differenza media sulla persona, 0-255):
# ~4 = identica, 6.9 = bozza 480p accettabile, 11 = ridisegnata (primo test del drago)
FIDELITY_OK = 6.0
FIDELITY_OK_P90 = 9.0
PHASES = {
    "clip": "preparo la clip vera",
    "plan": "Claude scrive il prompt (skill higgsfield-vfx)",
    "reference": "genero l'immagine di riferimento",
    "cost": "controllo i crediti",
    "generate": "Seedance genera la clip (qualche minuto)",
    "download": "scarico il risultato",
    "upscale": "porto la clip AI a 1080p (ByteDance, ~1-2 crediti)",
    "masks": "ritaglio la tua sagoma (in locale)",
    "compose": "allineo, coloro e fondo nel video",
    "review": "Claude rivede il risultato",
    "done": "pronto",
}

_LOCK = threading.RLock()


class VfxError(RuntimeError):
    pass


class Shot(BaseModel):
    id: str
    start_ms: int = Field(ge=0)  # tempo del raw
    dur_ms: int = Field(ge=500, le=GEN_MS)  # chiesto <= 3 s; si allunga se l'effetto dura di più
    request: str
    asked_ms: int = 0  # durata chiesta dal creator (dur_ms può allungarsi fino a 4 s)
    protect: bool = True
    quality: Literal["draft", "cheap", "hd720", "hd", "uhd", "api720", "api1080"] = "draft"
    status: Literal["running", "done", "error"] = "running"
    phase: str = "clip"
    log: str = ""
    error: str | None = None
    title: str = ""
    plan: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    credits: float = 0.0
    usd: float = 0.0  # spesa sulle API a consumo
    attempt: int = 1
    fix_prompt: str | None = None
    final: str | None = None  # nome del file in work/vfx/<id>/
    sheet: str | None = None
    enabled: bool = False  # nella timeline (preview + render)
    created_at: str = ""


class VfxFile(BaseModel):
    shots: list[Shot] = Field(default_factory=list)


# --- file vfx.json ---------------------------------------------------------------------


def load(project_dir: Path) -> VfxFile:
    p = project_dir / VFX_FILE
    if not p.exists():
        return VfxFile()
    return VfxFile.model_validate_json(p.read_text(encoding="utf-8"))


def save(project_dir: Path, data: VfxFile) -> None:
    p = project_dir / VFX_FILE
    tmp = p.with_suffix(".partial")
    tmp.write_text(data.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def edit(project_dir: Path, shot_id: str, **fields: Any) -> Shot:
    """Aggiorna un colpo (thread del lavoro ed endpoint lo fanno insieme: lock + rilettura)."""
    with _LOCK:
        data = load(project_dir)
        for i, s in enumerate(data.shots):
            if s.id == shot_id:
                data.shots[i] = s.model_copy(update=fields)
                save(project_dir, data)
                return data.shots[i]
    raise VfxError(f"colpo {shot_id} non trovato")


def get(project_dir: Path, shot_id: str) -> Shot:
    for s in load(project_dir).shots:
        if s.id == shot_id:
            return s
    raise VfxError(f"colpo {shot_id} non trovato")


def add(
    project_dir: Path, *, start_ms: int, dur_ms: int, request: str, protect: bool = True,
    quality: str = "draft", camera_ms: int,
) -> Shot:  # fmt: skip
    request = request.strip()
    if not request:
        raise VfxError("scrivi cosa vuoi vedere nel video")
    if quality not in QUALITIES:
        raise VfxError(f"qualità sconosciuta: {quality}")
    dur_ms = max(500, min(MAX_EFFECT_MS, int(dur_ms)))
    start_ms = max(0, int(start_ms))
    if start_ms + GEN_MS > camera_ms:
        raise VfxError("troppo vicino alla fine del video: servono almeno 4 s dopo il punto scelto")
    with _LOCK:
        data = load(project_dir)
        n = max(
            (int(s.id.split("_")[-1]) for s in data.shots if s.id.startswith("vfx_")), default=0
        )
        shot = Shot(
            id=f"vfx_{n + 1:03d}", start_ms=start_ms, dur_ms=dur_ms, asked_ms=dur_ms, request=request[:1200],
            protect=protect, quality=quality,  # type: ignore[arg-type]
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )  # fmt: skip
        data.shots.append(shot)
        save(project_dir, data)
    return shot


TRASH_DIR = "_cestino"


def remove(project_dir: Path, shot_id: str) -> Path | None:
    """Toglie la clip dall'elenco; i suoi file vanno nel cestino (work/vfx/_cestino/), non
    vengono cancellati: una clip costa crediti e una cancellazione per sbaglio è già successa.
    Il suo vfx.json resta accanto ai file, così la clip si può rimettere."""
    with _LOCK:
        data = load(project_dir)
        gone = [s for s in data.shots if s.id == shot_id]
        data.shots = [s for s in data.shots if s.id != shot_id]
        save(project_dir, data)
    src = shot_dir(project_dir, shot_id)
    if not src.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = src.parent / TRASH_DIR / f"{shot_id}-{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    if gone:
        (dest / "shot.json").write_text(gone[0].model_dump_json(indent=2), encoding="utf-8")
    return dest


def shot_dir(project_dir: Path, shot_id: str) -> Path:
    return project_dir / "work" / WORK_DIR / shot_id


# --- Higgsfield CLI --------------------------------------------------------------------


def hf_cli(args: list[str], timeout: int = 1800) -> Any:
    """`higgsfield ... --json` -> JSON. Errori chiari (sessione scaduta, piano, crediti)."""
    exe = shutil.which("higgsfield")
    if exe is None:
        raise VfxError("CLI Higgsfield non trovata: npm i -g @higgsfield/cli")
    try:
        proc = subprocess.run(
            [exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise VfxError(f"Higgsfield non ha risposto entro {timeout // 60} minuti") from exc
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        msg = (proc.stderr or out).strip()
        low = msg.lower()
        if "expired" in low or "not authenticated" in low or "login" in low:
            raise VfxError("Higgsfield: sessione scaduta. Premi «Ricollega Higgsfield»")
        if "plan required" in low:
            plans = re.findall(r'"([A-Za-z]+)"', msg)
            raise VfxError(
                "Questa qualità non è nel tuo piano Higgsfield: serve il piano "
                f"{' o '.join(plans) or 'superiore'}. Nessun credito scalato."
            )
        raise VfxError(f"Higgsfield: {msg[-300:]}")
    for start in (i for i, ch in enumerate(out) if ch in "{["):
        try:
            return json.loads(out[start:])
        except ValueError:
            continue
    url = re.search(r"https://\S+?\.(?:mp4|mov|webm|png|jpe?g|webp)", out)
    if url:
        return {"result_url": url.group(0)}
    raise VfxError(f"risposta di Higgsfield non leggibile: {out[-200:]}")


def result_url(data: Any) -> str | None:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None
    url = data.get("result_url") or data.get("url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    for key in ("results", "jobs", "result", "outputs", "videos", "images", "items", "output"):
        sub = data.get(key)
        if sub:
            found = result_url(sub)
            if found:
                return found
    return None


def download(url: str, dest: Path) -> None:
    import ssl

    import httpx
    import truststore

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(verify=ctx, timeout=300, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(r.content)
        tmp.replace(dest)


API_MAX_USD = 6.0  # tetto per singola generazione via API


def api_usd(quality: str, size: tuple[int, int], seconds: float) -> float:
    """Costo stimato (formula ufficiale): ingresso + uscita, stessa durata della clip."""
    q = QUALITIES[quality]
    w, h = (720, 1280) if q["resolution"] == "720p" else (1080, 1920)
    if size[0] > size[1]:
        w, h = h, w
    tokens = -(-int(w * h * (seconds * 2) * 24) // 1024)
    return round(tokens / 1000 * q["usd_per_ktok"], 2)


def api_key() -> str:
    import os

    from dotenv import dotenv_values

    from .images import REPO_ROOT

    env = {**dotenv_values(REPO_ROOT / ".env"), **os.environ}
    key = (env.get("HF_KEY") or env.get("Highsfield_API_KEY") or "").strip()
    if ":" not in key:
        raise VfxError("chiave API Higgsfield mancante: HF_KEY=key-id:key-secret nel file .env")
    return key


def api_generate(quality: str, prompt: str, clip: Path, ref: Path | None) -> str:
    """Seedance 2.5 Video Edit via API ufficiale (SDK higgsfield-client) -> URL del video."""
    import os

    import higgsfield_client as hc
    import truststore

    truststore.inject_into_ssl()  # certificati di Windows (TLS intercettato su questo PC)
    os.environ["HF_KEY"] = api_key()
    q = QUALITIES[quality]
    args: dict[str, Any] = {"prompt": prompt, "video_url": hc.upload_file(str(clip)),
                            "resolution": q["resolution"], "generate_audio": False}  # fmt: skip
    if ref is not None:
        args["image_urls"] = [hc.upload_file(str(ref))]
    try:
        res = hc.subscribe(q["api"], arguments=args)
    except Exception as exc:
        msg = str(exc).replace(os.environ["HF_KEY"], "[chiave]")
        if "credit" in msg.lower() or "balance" in msg.lower() or "402" in msg:
            raise VfxError(
                "saldo API Higgsfield insufficiente: ricarica su open.higgsfield.ai"
            ) from exc
        raise VfxError(f"API Higgsfield: {msg[:300]}") from exc
    url = result_url(res) or (
        (res.get("video") or {}).get("url") if isinstance(res, dict) else None
    )
    if not url:
        raise VfxError(f"l'API non ha restituito il video: {str(res)[:200]}")
    return url


UPSCALE_JOB = "bytedance_video_upscale"  # preset "aigc": pensato per i video generati dall'AI


def upscale_args(gen: Path, portrait: bool) -> list[str]:
    """Upscaler video ByteDance su Higgsfield: coerente nel tempo, conserva la texture (provato
    contro Real-ESRGAN in locale: quello rende le scaglie "di plastica" e impiega ~30 s a
    fotogramma su questo PC). La persona nel composito è già la ripresa vera a 1080p."""
    return [UPSCALE_JOB, "--video-references", str(gen), "--resolution", "1080p",
            "--preset", "aigc", "--model_version", "standard", "--fps", "24"]  # fmt: skip


def video_args(
    quality: str, prompt: str, clip: Path, ref: Path | None, aspect: str,
    start: Path | None = None, end: Path | None = None,
) -> list[str]:  # fmt: skip
    """Il primo e l'ultimo fotogramma VERI (senza effetto) come start/end image: Seedance sui
    tempi è instabile e tende a mettere l'elemento già al primo fotogramma e a lasciarlo
    all'ultimo; con le due immagini vincolate deve partire e tornare alla stanza com'è."""
    q = QUALITIES[quality]
    args = [q["job"], *q["args"], "--duration", str(GEN_MS // 1000), "--aspect_ratio", aspect,
            "--generate_audio", "false", "--prompt", prompt, "--video-references", str(clip)]  # fmt: skip
    if ref is not None:
        args += ["--image-references", str(ref)]
    if start is not None:
        args += ["--start-image", str(start)]
    if end is not None:
        args += ["--end-image", str(end)]
    return args


# --- richieste alla skill ---------------------------------------------------------------


def plan_request(
    shot: Shot, frame: Path, transcript: str, portrait: bool, size: tuple[int, int]
) -> str:
    fmt = "9:16 verticale" if portrait else "16:9 orizzontale"
    if QUALITIES[shot.quality].get("api"):
        ends = ("Modello: Seedance 2.5 Video Edit (vera modifica: ciò che non nomini resta com'è; "
                "niente start/end frame): metti nel prompt l'inizio con la stanza vuota e l'uscita "
                "fisica completa prima della fine.")  # fmt: skip
    else:
        ends = ("Il primo e l'ultimo fotogramma veri di Video 1 (stanza senza effetto) vengono passati "
                "come start frame ed end frame vincolati: scrivi che la clip inizia e finisce "
                "esattamente come quei fotogrammi.")  # fmt: skip
    prot = "sì (default)" if shot.protect else "no: il creator l'ha spenta"
    return f"""Usa la skill higgsfield-vfx. Job: plan.
Richiesta del creator: «{shot.request}»
Frame iniziale della clip (guardalo con Read): {frame}
Formato: {fmt}, {size[0]}x{size[1]}, ripresa vera del creator.
Durata dell'effetto: {shot.dur_ms / 1000:.1f} s. La clip inviata a Seedance dura {GEN_MS // 1000} s ma ne usiamo
solo i primi {shot.dur_ms / 1000:.1f} s: l'effetto deve essere completamente finito e sparito entro
{max(0.5, shot.dur_ms / 1000 - 0.4):.1f} s (Seedance tende ad allungare le azioni su tutta la clip: comprimi i tempi
e dì esplicitamente che dopo quel secondo la stanza resta com'era fino alla fine dei {GEN_MS // 1000} s).
Parlato in questi secondi: «{transcript or "(silenzio)"}»
Protezione persona richiesta dal creator: {prot}. Se è "no", rispettala: protect_person=false.
Qualità: {QUALITIES[shot.quality]["label"]}. La clip vera è "Video 1"; l'eventuale immagine di
riferimento sarà "Image 1". {ends} Scrivi il prompt nel formato ufficiale di references/prompting.md.
Rispondi solo con il JSON del job plan."""


def review_request(shot: Shot, sheet: Path, prompt: str, protect: bool) -> str:
    return f"""Usa la skill higgsfield-vfx. Job: review.
Richiesta del creator: «{shot.request}»
Foglio prima/dopo (guardalo con Read): {sheet}
Riga in alto = ripresa originale, riga in basso = take AI già composta, stessi istanti.
Protezione persona: {"attiva (la persona in basso è quella vera rimessa sopra)" if protect else "spenta"}.
Prompt usato: {prompt}
Rispondi solo con il JSON del job review."""


# --- frame e video con ffmpeg ------------------------------------------------------------


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise VfxError("ffmpeg non trovato nel PATH")
    return exe


def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise VfxError(f"{what}: {proc.stderr.decode('utf-8', 'replace').strip()[-300:]}")


def color_tags(path: Path) -> dict[str, str]:
    """Spazio colore del file (per rileggere e riscrivere i pixel senza spostamenti)."""
    exe = shutil.which("ffprobe")
    if exe is None:
        return {}
    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_space,color_primaries,color_transfer,color_range", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    try:
        st = json.loads(proc.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError):
        return {}
    return {k: v for k, v in st.items() if isinstance(v, str) and v != "unknown"}


def _setparams(tags: dict[str, str]) -> str:
    """Etichette colore sui fotogrammi (x264 le scrive solo se arrivano dal filtro)."""
    parts = [f"{k}={tags[t]}" for k, t in (("colorspace", "color_space"),
             ("color_primaries", "color_primaries"), ("color_trc", "color_transfer"),
             ("range", "color_range")) if tags.get(t)]  # fmt: skip
    return ",setparams=" + ":".join(parts) if parts else ""


def _matrix(tags: dict[str, str]) -> str | None:
    cs = tags.get("color_space", "")
    return "bt2020" if cs.startswith("bt2020") else ("bt709" if cs == "bt709" else None)


def read_frames(
    path: Path, w: int, h: int, n: int, tags: dict[str, str] | None = None
) -> Iterator[Any]:
    """Fotogrammi RGB (numpy h x w x 3) a 30 fps, al massimo n."""
    import numpy as np

    m = _matrix(tags or {})
    scale = f"scale={w}:{h}:flags=bicubic" + (f":in_color_matrix={m}" if m else "")
    proc = subprocess.Popen(
        [_ffmpeg(), "-v", "error", "-nostdin", "-i", str(path), "-vf", f"fps={FPS},{scale},format=rgb24",
         "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    size = w * h * 3
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


class _Writer:
    def __init__(self, dest: Path, w: int, h: int, tags: dict[str, str]):
        m = _matrix(tags)
        vf = "scale=out_range=tv" + (f":out_color_matrix={m}" if m else "") + ",format=yuv420p"
        vf += _setparams(tags)
        meta = []
        for key, flag in (("color_space", "-colorspace"), ("color_primaries", "-color_primaries"),
                          ("color_transfer", "-color_trc"), ("color_range", "-color_range")):  # fmt: skip
            if tags.get(key):
                meta += [flag, tags[key]]
        self.proc = subprocess.Popen(
            [_ffmpeg(), "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-vf", vf, "-c:v", "libx264",
             "-preset", "medium", "-crf", "16", "-g", str(FPS), *meta, str(dest)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip

    def write(self, frame: Any) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(frame.tobytes())

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        if self.proc.wait() != 0:
            raise VfxError(f"scrittura del video: {err.strip()[-300:]}")


# --- composito ---------------------------------------------------------------------------


RVM_FILE = "rvm_mobilenetv3_fp32.onnx"  # Robust Video Matting (GPL-3.0), fuori da git
RVM_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/" + RVM_FILE


def rvm_model() -> Path:
    from .images import MODELS_DIR

    path = MODELS_DIR / RVM_FILE
    if not (path.is_file() and path.stat().st_size > 1_000_000):
        download(RVM_URL, path)
    return path


def rvm_matte(video: Path, n: int | None = None) -> tuple[Path, int]:
    """Sagoma della persona fotogramma per fotogramma con Robust Video Matting: bordi e capelli
    precisi, stabile nel tempo (memoria ricorrente), a piena risoluzione. Stesso formato delle
    maschere MediaPipe (JPG, bianco = sfondo) in <video>-rvm/. In locale, gratis."""
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    dest = video.with_name(video.stem + "-rvm")
    done = dest / "done.txt"
    if done.exists():
        return dest, int(done.read_text())
    dest.mkdir(parents=True, exist_ok=True)
    tags = color_tags(video)
    exe = shutil.which("ffprobe")
    w, h = 1080, 1920
    if exe:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=False,
        ).stdout.strip().split(",")  # fmt: skip
        if len(out) == 2 and all(x.isdigit() for x in out):
            w, h = int(out[0]), int(out[1])
    sess = ort.InferenceSession(str(rvm_model()), providers=["CPUExecutionProvider"])
    rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4
    ratio = np.array([0.25 if max(w, h) >= 1280 else 0.4], np.float32)
    count = 0
    for frame in read_frames(video, w, h, n or 100000, tags):
        src = frame.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        _, pha, *rec = sess.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1],
                                       "r3i": rec[2], "r4i": rec[3], "downsample_ratio": ratio})  # fmt: skip
        count += 1
        a = np.clip(pha[0, 0], 0.0, 1.0)
        Image.fromarray(((1.0 - a) * 255).astype(np.uint8)).save(
            dest / f"{count:05d}.jpg", quality=95
        )
    done.write_text(str(count))
    return dest, count


def _person_alpha(mask_file: Path | None, w: int, h: int, grow: int) -> Any:
    """Alpha della persona (1 = persona) da una maschera (bianco = sfondo): RVM a piena
    risoluzione così com'è, MediaPipe (metà risoluzione) allargata e ammorbidita."""
    import numpy as np
    from PIL import Image, ImageFilter

    if mask_file is None or not mask_file.is_file():
        return None
    im = Image.open(mask_file).convert("L")
    if im.size == (w, h):
        return 1.0 - np.asarray(im, np.float32)[..., None] / 255.0
    if grow > 0:  # allarga un po' la persona: niente bordo "fantasma" della persona AI
        im = im.filter(ImageFilter.MinFilter(grow * 2 + 1))
    im = im.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
    return 1.0 - np.asarray(im, np.float32)[..., None] / 255.0


def person_fidelity(source: Path, gen: Path, masks: Path) -> dict[str, Any] | None:
    """Quanto la persona nella clip AI è uguale a quella vera (dopo allineamento e colore)."""
    import numpy as np

    w, h = 180, 320
    files = sorted(masks.glob("*.jpg"))
    src = list(read_frames(source, w, h, 110, color_tags(source)))
    gen_ = list(read_frames(gen, w, h, 125, color_tags(gen)))
    if not src or not gen_ or not files:
        return None
    alphas = []
    for i in range(len(src)):
        a = _person_alpha(files[min(i, len(files) - 1)], 1080, 1920, 0)
        alphas.append(_down(a[..., 0], w, h)[..., None] if a is not None else None)
    if any(a is None for a in alphas):
        return None
    k = best_offset(src, gen_, alphas)
    gain, off = color_transfer(src, gen_, alphas, k)
    vals = []
    for i, s in enumerate(src):
        j = i + k
        core = alphas[i][..., 0] > 0.95
        if not 0 <= j < len(gen_) or core.sum() < 50:
            continue
        g = np.clip(gen_[j].astype(np.float32) * gain + off, 0, 255)
        vals.append(float(np.abs(g - s.astype(np.float32)).mean(axis=2)[core].mean()))
    if not vals:
        return None
    return {
        "median": round(float(np.median(vals)), 1),
        "p90": round(float(np.percentile(vals, 90)), 1),
    }


GHOST_SHAPE = 0.8  # differenza di forma del volto oltre cui la testa AI si è spostata


def _shape(x: Any) -> Any:
    import numpy as np

    g = x.astype(np.float32).mean(axis=2)
    return np.abs(np.diff(g, axis=1, prepend=g[:, :1])) + np.abs(np.diff(g, axis=0, prepend=g[:1]))


def face_shape_diffs(source: Path, gen: Path, masks: Path, k: int, n: int) -> list[float]:
    """Per ogni fotogramma: quanto la FORMA del volto AI differisce dalla vera (contrasto locale
    normalizzato: la luce del fuoco sul viso non conta). ~0.4 = stesso volto; > GHOST_SHAPE = la
    testa AI si è mossa diversamente (rischio "testa fantasma")."""
    import numpy as np

    w, h = 270, 480
    files = sorted(masks.glob("*.jpg"))
    src = list(read_frames(source, w, h, n, color_tags(source)))
    gen_ = list(read_frames(gen, w, h, n + max(k, 0) + 2, color_tags(gen)))
    out: list[float] = []
    for i, s in enumerate(src):
        j = i + k
        a = _person_alpha(files[min(i, len(files) - 1)], 1080, 1920, 0) if files else None
        if a is None or not 0 <= j < len(gen_):
            out.append(0.0)
            continue
        a = _down(a[..., 0], w, h)
        ys = np.nonzero(a > 0.9)[0]
        if ys.size == 0:
            out.append(0.0)
            continue
        fm = np.zeros_like(a, bool)
        fm[ys.min() : ys.min() + int(h * 0.28)] = True
        fm &= a > 0.95
        if fm.sum() < 100:
            out.append(0.0)
            continue
        gs, ss = _shape(gen_[j]), _shape(s)
        out.append(
            float(np.abs(gs / (gs[fm].mean() + 1e-3) - ss / (ss[fm].mean() + 1e-3))[fm].mean())
        )
    return out


def best_offset(src: list[Any], gen: list[Any], weights: list[Any] | None, span: int = 8) -> int:
    """Di quanti fotogrammi è spostata la clip AI rispetto alla vera (persona come riferimento)."""
    import numpy as np

    best, best_err = 0, float("inf")
    n = min(len(src), 45)
    for k in range(-span, span + 1):
        errs = []
        for i in range(n):
            j = i + k
            if 0 <= j < len(gen):
                d = np.abs(src[i].astype(np.float32) - gen[j].astype(np.float32)).mean(axis=2)
                wgt = weights[i][..., 0] if weights else None
                errs.append(
                    float((d * wgt).sum() / max(wgt.sum(), 1e-3))
                    if wgt is not None
                    else float(d.mean())
                )
        if len(errs) >= n // 2 and errs:
            e = float(np.mean(errs)) + abs(k) * 0.05  # a parità, meglio nessuno spostamento
            if e < best_err:
                best, best_err = k, e
    return best


def color_transfer(
    src: list[Any], gen: list[Any], weights: list[Any] | None, k: int
) -> tuple[Any, Any]:
    """Guadagno e offset per canale: porta i colori della clip AI su quelli veri (sulla persona,
    che c'è uguale in entrambe), così l'elemento nuovo prende la stessa luce/grading."""
    import numpy as np

    s_px, g_px = [], []
    for i, s in enumerate(src):
        j = i + k
        if not 0 <= j < len(gen):
            continue
        if weights:
            sel = weights[i][..., 0] > 0.6
            if sel.sum() < 50:
                continue
            s_px.append(s[sel])
            g_px.append(gen[j][sel])
        else:
            s_px.append(s.reshape(-1, 3))
            g_px.append(gen[j].reshape(-1, 3))
    if not s_px:
        return np.ones(3, np.float32), np.zeros(3, np.float32)
    sa = np.concatenate(s_px).astype(np.float32)
    ga = np.concatenate(g_px).astype(np.float32)
    gain = np.clip(sa.std(0) / np.maximum(ga.std(0), 1e-3), 0.75, 1.35)
    off = sa.mean(0) - gain * ga.mean(0)
    return gain.astype(np.float32), np.clip(off, -40, 40).astype(np.float32)


def _down(x: Any, w: int, h: int) -> Any:
    import numpy as np
    from PIL import Image

    if x.ndim == 2:
        return np.asarray(Image.fromarray(x.astype(np.float32), "F").resize((w, h), Image.BILINEAR))
    return np.stack([_down(x[..., c], w, h) for c in range(x.shape[2])], axis=2)


def fill_behind(img: Any, hole: Any) -> Any:
    """Ricostruisce la scena AI dove c'era la persona AI (push-pull dai pixel attorno): così
    dietro la persona vera continua il drago/il muro illuminato, non il muro com'era."""
    import numpy as np

    h, w = hole.shape
    qw, qh = max(16, w // 2), max(16, h // 2)
    c = _down(img, qw, qh)
    wt = 1.0 - np.clip(_down(hole, qw, qh), 0.0, 1.0)
    wt = (wt > 0.98).astype(np.float32)  # solo pixel puliti come sorgente
    levels = []
    cc, ww = c * wt[..., None], wt
    while min(ww.shape) > 4:
        levels.append((cc, ww))
        hh, w2 = ww.shape[0] // 2 * 2, ww.shape[1] // 2 * 2
        cc = cc[:hh, :w2].reshape(hh // 2, 2, w2 // 2, 2, 3).mean(axis=(1, 3))
        ww = ww[:hh, :w2].reshape(hh // 2, 2, w2 // 2, 2).mean(axis=(1, 3))
    filled = cc / np.maximum(ww, 1e-4)[..., None]
    for cc, ww in reversed(levels):
        up = _down(filled, ww.shape[1], ww.shape[0])
        filled = cc + up * (1.0 - ww)[..., None]  # colore*peso + riempimento dal livello sopra
    full = _down(filled, w, h)
    m = hole[..., None]
    return img * (1.0 - m) + full * m


def behind_hole(a: Any, ag: Any) -> Any:
    """Zona da ricostruire: TUTTA la persona AI che resta fuori dalla persona vera (più larga,
    o spostata perché a bassa risoluzione Seedance non copia i movimenti: senza questo resta
    una "testa fantasma"). Persona AI = alpha > 0.3: lo scontorno vede in parte anche la
    creatura come primo piano, ma con confidenza bassa, e quella non va toccata."""
    import numpy as np
    from PIL import Image, ImageFilter

    h, w = a.shape[:2]
    qw, qh = max(16, w // 2), max(16, h // 2)
    a_q = _down(a[..., 0], qw, qh)
    band = (_down(ag[..., 0], qw, qh) > 0.3) & (a_q < 0.5)  # persona AI fuori dalla vera
    # entro ~80 px dal tuo contorno (dilatazione a 1/8: il filtro a piena scala è lentissimo)
    a8 = Image.fromarray(
        ((_down(a[..., 0], max(4, w // 8), max(4, h // 8)) > 0.5) * 255).astype(np.uint8)
    )
    near = a8.filter(ImageFilter.MaxFilter(21)).resize((qw, qh), Image.NEAREST)
    band &= np.asarray(near) > 0
    # i pochi pixel AI attaccati al tuo contorno (~12 px) si lasciano: sono capelli/bordo che
    # si fondono con i tuoi; sostituirli col muro creava l'alone chiaro. Si ricostruisce solo
    # la persona AI staccata da te (testa fantasma quando l'AI si muove diversamente).
    a4 = Image.fromarray(
        ((_down(a[..., 0], max(4, w // 4), max(4, h // 4)) > 0.5) * 255).astype(np.uint8)
    )
    touch = a4.filter(ImageFilter.MaxFilter(7)).resize((qw, qh), Image.NEAREST)
    band &= np.asarray(touch) == 0
    q = Image.fromarray((band * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    q = q.filter(ImageFilter.GaussianBlur(1.0))
    return _down(np.asarray(q, np.float32) / 255.0, w, h)


def relight_map(sf: Any, gf: Any, w: int, h: int) -> Any:
    """Rapporto di luce morbido AI/vera (es. il bagliore del fuoco sulla parete), per canale."""
    import numpy as np
    from PIL import Image, ImageFilter

    small = (max(8, w // 8), max(8, h // 8))

    def blur(x: Any) -> Any:
        im = Image.fromarray(np.clip(x, 0, 255).astype(np.uint8)).resize(small, Image.BILINEAR)
        return np.asarray(im.filter(ImageFilter.GaussianBlur(6)), np.float32)

    ratio = np.clip((blur(gf) + 8.0) / (blur(sf) + 8.0), 0.6, 2.5)
    up = Image.fromarray(np.clip(ratio * 100, 0, 255).astype(np.uint8)).resize(
        (w, h), Image.BILINEAR
    )
    return np.asarray(up, np.float32) / 100.0


def effect_end(
    src: list[Any], gen: list[Any], weights: list[Any] | None, k: int, gain: Any, off: Any
) -> int | None:
    """Ultimo fotogramma in cui la clip AI è diversa dalla vera fuori dalla persona (= l'effetto
    è ancora in scena). Seedance tende ad allungare l'azione su tutta la clip: così non si taglia
    a metà fiammata."""
    import numpy as np

    diffs = []
    for i, s in enumerate(src):
        j = i + k
        if not 0 <= j < len(gen):
            diffs.append(None)
            continue
        g = np.clip(gen[j].astype(np.float32) * gain + off, 0, 255)
        d = np.abs(g - s.astype(np.float32)).mean(axis=2)
        bg = 1.0 - weights[i][..., 0] if weights else np.ones(d.shape, np.float32)
        diffs.append(float((d * bg).sum() / max(bg.sum(), 1e-3)))
    vals = [x for x in diffs if x is not None]
    if not vals:
        return None
    base = min(vals)
    thr = max(6.0, base * 2.5)
    last = None
    for i, x in enumerate(diffs):
        if x is not None and x > thr:
            last = i
    return last


def compose(
    source: Path, gen: Path, dest: Path, sheet: Path, *, dur_ms: int, size: tuple[int, int],
    masks: Path | None, protect: bool, gen_masks: Path | None = None, extend_ms: int = 0,
) -> dict[str, Any]:  # fmt: skip
    """Clip finale (dur_ms) = AI allineata e colorata, con la persona vera sopra se protect.

    gen_masks = sagoma della persona nella clip AI (a 30 fps): dove l'AI ha disegnato la persona
    un po' più grande o spostata si usa la ripresa vera, così non spuntano capelli "doppi"."""
    import numpy as np
    from PIL import Image

    w, h = size
    n = max(1, round(dur_ms / 1000 * FPS))
    tags = color_tags(source)
    gtags = color_tags(gen)
    sw, sh = (54, 96) if h >= w else (96, 54)
    s_small = list(read_frames(source, sw, sh, n + 10, tags))
    g_small = list(read_frames(gen, sw, sh, n + 20, gtags))
    if len(g_small) < n // 2:
        raise VfxError("la clip generata è troppo corta o illeggibile")
    mfiles = sorted(masks.glob("*.jpg")) if masks else []
    w_small = [
        _person_alpha(mfiles[i] if i < len(mfiles) else None, sw, sh, 0) for i in range(len(s_small))
    ] if mfiles else None  # fmt: skip
    if w_small and any(x is None for x in w_small):
        w_small = None
    k = best_offset(s_small, g_small, w_small)
    gain, off = color_transfer(s_small, g_small, w_small, k)
    # ricostruzione dietro la persona SOLO nei fotogrammi dove la testa AI si è spostata (testa
    # fantasma): altrove la creatura che ti tocca (es. il drago che entra) verrebbe cancellata
    ghost: set[int] = set()
    if protect and gen_masks is not None and masks is not None:
        shape = face_shape_diffs(source, gen, masks, k, round(extend_ms / 1000 * FPS) or n)
        # mediana su 5 fotogrammi: Seedance genera a 24 fps e la conversione a 30 crea un
        # picco isolato ogni 5 fotogrammi; la testa fantasma vera dura molti fotogrammi di fila
        smooth = [sorted(shape[max(0, i - 2): i + 3])[len(shape[max(0, i - 2): i + 3]) // 2]
                  for i in range(len(shape))]  # fmt: skip
        for i, v in enumerate(smooth):
            if v > GHOST_SHAPE:
                ghost.update(range(max(0, i - 3), i + 4))  # ±3 fotogrammi: niente sfarfallio
    n_req = n
    if extend_ms > dur_ms:  # l'effetto finisce dopo la durata chiesta: si allunga (stesso costo)
        s_all = list(read_frames(source, sw, sh, round(extend_ms / 1000 * FPS), tags))
        g_all = list(read_frames(gen, sw, sh, round(extend_ms / 1000 * FPS) + 20, gtags))
        w_all = [_person_alpha(mfiles[i] if i < len(mfiles) else None, sw, sh, 0)
                 for i in range(len(s_all))] if mfiles else None  # fmt: skip
        if w_all and any(x is None for x in w_all):
            w_all = None
        last = effect_end(s_all, g_all, w_all, k, gain, off)
        avail = min(len(s_all), len(g_all) - max(k, 0))
        if last is not None and last + 1 > n:
            n = max(n, min(avail, last + 1 + FADE_FRAMES + 3))

    src_it = read_frames(source, w, h, n, tags)
    gen_frames = read_frames(gen, w, h, n + max(k, 0) + 2, gtags)
    for _ in range(max(k, 0)):  # la clip AI è in anticipo: si saltano i suoi primi fotogrammi
        next(gen_frames, None)
    cur = next(gen_frames, None)
    gidx = max(k, 0)  # indice (a 30 fps) del fotogramma AI in uso
    gfiles = sorted(gen_masks.glob("*.jpg")) if gen_masks else []
    writer = _Writer(dest, w, h, tags)
    picks = {round(n * f) for f in (0.15, 0.4, 0.65, 0.9)}
    shots: list[tuple[Any, Any]] = []
    try:
        for i, s in enumerate(src_it):
            # in ritardo (k < 0): si ripete il primo fotogramma AI finché non "arriva"
            if i + min(k, 0) > 0:
                nxt = next(gen_frames, None)
                if nxt is not None:
                    cur, gidx = nxt, gidx + 1
            g = s if cur is None else cur
            gf = np.clip(g.astype(np.float32) * gain + off, 0, 255)
            sf = s.astype(np.float32)
            if protect:
                a = _person_alpha(mfiles[i] if i < len(mfiles) else None, w, h, 3)
                ag = _person_alpha(gfiles[gidx], w, h, 0) if gidx < len(gfiles) else None
                if a is not None:
                    # 1) scena AI senza la persona AI (Seedance la ridisegna un po' più larga):
                    #    dietro di te continua il drago / il muro illuminato, niente alone
                    plate = gf
                    rmap = relight_map(sf, gf, w, h)
                    if ag is not None and i in ghost:
                        hole = behind_hole(a, ag)
                        ys, xs = np.nonzero(hole > 0.02)
                        if ys.size:  # si lavora solo nel riquadro della striscia (veloce)
                            y0, y1 = max(0, ys.min() - 64), min(h, ys.max() + 65)
                            x0, x1 = max(0, xs.min() - 64), min(w, xs.max() + 65)
                            sub, hs = gf[y0:y1, x0:x1], hole[y0:y1, x0:x1]
                            fil = fill_behind(sub, hs)
                            # dove dietro c'è solo muro: il muro VERO (nitido) con la luce AI;
                            # dove c'è l'elemento nuovo (drago): la ricostruzione
                            # muro vero + la differenza AI/vera misurata tutto attorno e
                            # prolungata dentro (fusione senza cuciture: nessuna toppa visibile)
                            ssub = sf[y0:y1, x0:x1]
                            relit = np.clip(ssub + fill_behind(sub - ssub, hs), 0, 255)
                            cw, ch = x1 - x0, y1 - y0
                            diff = _down(
                                np.abs(fil - relit).mean(axis=2), max(2, cw // 8), max(2, ch // 8)
                            )
                            wr = _down(np.clip(1.0 - diff / 28.0, 0.0, 1.0), cw, ch)[..., None]
                            m = hs[..., None]
                            plate = gf.copy()
                            plate[y0:y1, x0:x1] = sub * (1 - m) + (relit * wr + fil * (1 - wr)) * m
                    # 2) light wrap: il bordo della persona prende la luce della scena AI
                    edge = np.clip(a * (1.0 - a) * 4.0, 0.0, 1.0)
                    lw = 1.0 + (rmap - 1.0) * edge * 0.8
                    gf = plate * (1 - a) + np.clip(sf * lw, 0, 255) * a
            wt = min(1.0, (i + 1) / FADE_FRAMES, (n - i) / FADE_FRAMES)
            out = np.clip(sf * (1 - wt) + gf * wt, 0, 255).astype(np.uint8)
            writer.write(out)
            if i in picks:
                shots.append((s.copy(), out.copy()))
    finally:
        writer.close()
    # foglio prima/dopo per la revisione (e per l'editor)
    tw = 270 if h > w else 480
    th = round(tw * h / w)
    board = Image.new("RGB", (tw * max(1, len(shots)), th * 2), "black")
    for c, (a_, b_) in enumerate(shots):
        board.paste(Image.fromarray(a_).resize((tw, th)), (c * tw, 0))
        board.paste(Image.fromarray(b_).resize((tw, th)), (c * tw, th))
    board.save(sheet, quality=88)
    return {"offset_frames": k, "dur_ms": round(n / FPS * 1000), "requested_frames": n_req,
            "rebuilt_frames": len(ghost),
            "gain": [round(float(x), 3) for x in gain],
            "offset": [round(float(x), 1) for x in off], "frames": n}  # fmt: skip


# --- il lavoro completo -------------------------------------------------------------------


def run_shot(
    project_dir: Path, shot_id: str, *, tl: Any, agent: Any, hf: Callable[..., Any] = hf_cli,
    fetch: Callable[[str, Path], None] = download,
    masks_fn: Callable[[Path], tuple[Path, int]] | None = None,
    source_fn: Callable[..., Path] | None = None,
) -> Shot:  # fmt: skip
    """Esegue tutto il flusso di un colpo, aggiornando vfx.json fase per fase."""
    from .render.preview import ensure_source

    shot = get(project_dir, shot_id)
    d = shot_dir(project_dir, shot_id)
    d.mkdir(parents=True, exist_ok=True)
    work = project_dir / "work"

    def step(phase: str, **kw: Any) -> Shot:
        return edit(project_dir, shot_id, phase=phase, log=PHASES.get(phase, phase), **kw)

    try:
        cam = tl.sources.camera
        v = cam.video
        portrait = v.display_height >= v.display_width
        size = (1080, 1920) if portrait else (1920, 1080)
        aspect = "9:16" if portrait else "16:9"
        src_raw = Path(cam.path_hint) if cam.path_hint else None
        if src_raw is None or not src_raw.is_file():
            raise VfxError(f"file camera non trovato: {cam.path_hint}")
        step("clip")
        end = shot.start_ms + GEN_MS
        source = (source_fn or ensure_source)(work, tl, src_raw, shot.start_ms, end, gain_db=0.0)
        clip = d / "input.mp4"
        frame = d / "frame.jpg"
        if not clip.exists():
            small = "scale=720:1280" if portrait else "scale=1280:720"
            _run([_ffmpeg(), "-v", "error", "-y", "-i", str(source), "-an", "-vf", small, "-c:v",
                  "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(clip)], "clip da inviare")  # fmt: skip
            _run([_ffmpeg(), "-v", "error", "-y", "-i", str(source), "-frames:v", "1", "-vf", small,
                  str(frame)], "frame iniziale")  # fmt: skip
        end_frame = d / "end.jpg"
        if not end_frame.exists():
            _run([_ffmpeg(), "-v", "error", "-y", "-sseof", "-0.08", "-i", str(clip), "-frames:v", "1",
                  "-update", "1", str(end_frame)], "frame finale")  # fmt: skip

        if shot.fix_prompt:
            plan = {**shot.plan, "prompt": shot.fix_prompt}
        else:
            step("plan")
            words = [w.text for w in tl.words if w.kind == "word"
                     and shot.start_ms <= w.start_ms < shot.start_ms + shot.dur_ms]  # fmt: skip
            raw = agent.ask_skill(plan_request(shot, frame, " ".join(words), portrait, size))
            plan = {
                "prompt": str(raw.get("prompt", "")).strip(),
                "protect_person": bool(raw.get("protect_person", shot.protect)) and shot.protect,
                "reference_image": raw.get("reference_image") or None,
                "risk": str(raw.get("risk", ""))[:400],
                "title": str(raw.get("title", ""))[:60],
            }
            if len(plan["prompt"]) < 40:
                raise VfxError("Claude non ha scritto un prompt valido")
        protect = bool(plan.get("protect_person", shot.protect))
        edit(project_dir, shot_id, plan=plan, title=plan.get("title") or shot.title)

        ref = None
        ref_cost = 0.0
        ref_spec = plan.get("reference_image")
        if isinstance(ref_spec, dict) and ref_spec.get("prompt"):
            ref = d / "ref.png"
            if not ref.exists():
                step("reference")
                ref_cost = 0.12
                data = hf(["generate", "create", REF_MODEL, "--aspect_ratio", "1:1",
                           "--prompt", str(ref_spec["prompt"]), "--wait", "--json"])  # fmt: skip
                url = result_url(data)
                if not url:
                    raise VfxError("Higgsfield non ha restituito l'immagine di riferimento")
                fetch(url, ref)

        step("cost")
        via_api = bool(QUALITIES[shot.quality].get("api"))
        usd = 0.0
        if via_api:  # API a consumo: niente crediti del piano, si paga in dollari
            credits = 0.0
            usd = api_usd(shot.quality, size, GEN_MS / 1000)
            if usd > API_MAX_USD:
                raise VfxError(f"costerebbe circa {usd:g} $ (tetto {API_MAX_USD:g} $): non genero")
        else:
            args = video_args(shot.quality, plan["prompt"], clip, ref, aspect, frame, end_frame)
            est = hf(["generate", "cost", *args, "--json"])
            credits = float(est.get("credits", 0)) if isinstance(est, dict) else 0.0
            cap = max(MAX_CREDITS, QUALITIES[shot.quality]["credits"] * 1.15)
            if credits > cap:
                raise VfxError(f"costerebbe {credits:g} crediti (tetto {cap:g}): non genero")

        # la sagoma della persona vera si calcola mentre Seedance genera (tempo nascosto)
        mres: dict[str, Any] = {}

        def _matte() -> None:
            try:
                mres["masks"] = (masks_fn or rvm_matte)(source)[0]
            except Exception as exc:  # noqa: BLE001 - riportato sotto
                mres["error"] = exc

        mt = threading.Thread(target=_matte, daemon=True)
        mt.start()

        step("generate")
        if via_api:
            url = api_generate(shot.quality, plan["prompt"], clip, ref)
        else:
            data = hf(["generate", "create", *args, "--wait", "--wait-timeout", "25m", "--json"])
            url = result_url(data)
        if not url:
            raise VfxError("Higgsfield non ha restituito la clip")
        gen = d / f"gen-{shot.attempt}.mp4"
        cur = get(project_dir, shot_id)
        step(
            "download",
            credits=round(cur.credits + credits + ref_cost, 2),
            usd=round(cur.usd + usd, 2),
        )
        fetch(url, gen)

        if QUALITIES[shot.quality].get("upscale"):
            # Seedance a 720p sul piano Starter -> 1080p prima del composito (se non riesce,
            # si va avanti con la clip a 720p: meglio una clip che nessuna)
            step("upscale")
            up = d / f"gen-{shot.attempt}-1080.mp4"
            try:
                uargs = upscale_args(gen, portrait)
                est = hf(["generate", "cost", *uargs, "--json"])
                ucost = float(est.get("credits", 0)) if isinstance(est, dict) else 0.0
                if ucost <= 4:
                    uurl = result_url(hf(["generate", "create", *uargs, "--wait",
                                          "--wait-timeout", "15m", "--json"]))  # fmt: skip
                    if uurl:
                        fetch(uurl, up)
                        gen = up
                        cur = get(project_dir, shot_id)
                        edit(project_dir, shot_id, credits=round(cur.credits + ucost, 2))
            except Exception as exc:  # noqa: BLE001 - l'upscale è un miglioramento facoltativo
                plan = {**plan, "upscale_error": str(exc)[:200]}
            plan = {**plan, "upscaled": gen == up}

        gen_masks = None
        step("masks")
        mt.join()
        masks = mres.get("masks")
        if masks is None and protect:
            raise VfxError(f"sagoma della persona non riuscita: {mres.get('error')}")
        # come fanno gli altri: se Seedance ha tenuto la persona fedele, la clip AI si usa così
        # com'è (niente ritaglio, niente bordi); se l'ha ridisegnata, si rimette quella vera
        fid = person_fidelity(source, gen, masks) if masks is not None else None
        mode = "direct"
        if protect and (fid is None or fid["median"] > FIDELITY_OK or fid["p90"] > FIDELITY_OK_P90):
            mode = "protected"
        protect = mode == "protected"
        plan = {**plan, "mode": mode, "fidelity": fid}
        if protect and masks is not None:
            gen30 = d / f"gen30-{shot.attempt}.mp4"  # stessa cadenza del composito
            _run([_ffmpeg(), "-v", "error", "-y", "-i", str(gen), "-an", "-vf",
                  f"fps={FPS},scale={size[0]}:{size[1]}", "-c:v", "libx264", "-crf", "18",
                  "-pix_fmt", "yuv420p", str(gen30)], "clip AI a 30 fps")  # fmt: skip
            try:
                gen_masks, _ = (masks_fn or rvm_matte)(gen30)
            except Exception:  # facoltativa: senza, resta la sagoma vera allargata
                gen_masks = None

        step("compose")
        final = d / f"final-{shot.attempt}.mp4"
        sheet = d / f"sheet-{shot.attempt}.jpg"
        asked = shot.asked_ms or shot.dur_ms
        info = compose(source, gen, final, sheet, dur_ms=asked, size=size, masks=masks,
                       protect=protect, gen_masks=gen_masks, extend_ms=GEN_MS)  # fmt: skip
        edit(project_dir, shot_id, final=final.name, sheet=sheet.name,
             dur_ms=max(asked, info["dur_ms"]), plan={**plan, "compose": info})  # fmt: skip

        step("review")
        try:
            rv = agent.ask_skill(review_request(shot, sheet, plan["prompt"], protect))
            review = {
                "verdict": rv.get("verdict")
                if rv.get("verdict") in ("ok", "retry", "fail")
                else "?",
                "issues": [str(x)[:200] for x in (rv.get("issues") or [])][:6],
                "fix_prompt": str(rv.get("fix_prompt") or "")[:4000],
            }
        except Exception as exc:  # la revisione non blocca: la clip c'è
            review = {
                "verdict": "?",
                "issues": [f"revisione non riuscita: {exc}"[:200]],
                "fix_prompt": "",
            }
        return edit(project_dir, shot_id, status="done", phase="done", log=PHASES["done"],
                    review=review, error=None)  # fmt: skip
    except Exception as exc:
        return edit(
            project_dir, shot_id, status="error", error=str(exc)[:500] or exc.__class__.__name__
        )


def retry(project_dir: Path, shot_id: str, use_fix: bool) -> Shot:
    s = get(project_dir, shot_id)
    if s.status == "running":
        raise VfxError("sta già generando")
    fix = (s.review.get("fix_prompt") or None) if use_fix else None
    return edit(project_dir, shot_id, status="running", phase="clip", error=None,
                attempt=s.attempt + 1, fix_prompt=fix, review={}, enabled=False)  # fmt: skip


# --- dentro il render ----------------------------------------------------------------------


def active(project_dir: Path) -> list[Shot]:
    return [s for s in load(project_dir).shots
            if s.enabled and s.final and (shot_dir(project_dir, s.id) / s.final).is_file()]  # fmt: skip


def bake(project_dir: Path, source: Path, start_ms: int, end_ms: int) -> Path:
    """Estratto della camera con dentro i colpi AI attivi nella finestra (cache per contenuto)."""
    shots = [s for s in active(project_dir)
             if s.start_ms < end_ms and s.start_ms + s.dur_ms > start_ms]  # fmt: skip
    if not shots:
        return source
    key = hashlib.sha1()
    for s in shots:
        f = shot_dir(project_dir, s.id) / str(s.final)
        key.update(f"{s.id}:{s.start_ms}:{f.stat().st_mtime_ns}".encode())
    dest = source.with_name(f"{source.stem}-vfx-{key.hexdigest()[:10]}.mp4")
    if dest.exists():
        return dest
    tags = color_tags(source)
    inputs: list[str] = ["-i", str(source)]
    chains, last = [], "0:v"
    for i, s in enumerate(shots, start=1):
        inputs += ["-i", str(shot_dir(project_dir, s.id) / str(s.final))]
        off = (s.start_ms - start_ms) / 1000
        trim = f"trim=start={-off:.3f}," if off < 0 else ""
        chains.append(f"[{i}:v]{trim}setpts=PTS-STARTPTS+{max(off, 0):.3f}/TB[a{i}]")
        chains.append(f"[{last}][a{i}]overlay=eof_action=pass:repeatlast=0[v{i}]")
        last = f"v{i}"
    chains.append(f"[{last}]format=yuv420p{_setparams(tags)}[vout]")
    last = "vout"
    meta = []
    for key_, flag in (("color_space", "-colorspace"), ("color_primaries", "-color_primaries"),
                       ("color_transfer", "-color_trc"), ("color_range", "-color_range")):  # fmt: skip
        if tags.get(key_):
            meta += [flag, tags[key_]]
    tmp = dest.with_name(dest.stem + ".partial.mp4")
    _run([_ffmpeg(), "-v", "error", "-nostdin", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", f"[{last}]", "-map", "0:a?", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
          "-crf", "16", "-g", str(FPS), *meta, "-c:a", "copy", str(tmp)],
         "clip AI nel video")  # fmt: skip
    tmp.replace(dest)
    return dest
