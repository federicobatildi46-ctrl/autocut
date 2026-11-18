"""Pannello Immagini: cerca foto vere sul web, le scarica e le scontorna in locale.

- ricerca: Bing Immagini (tutto il web, anche solo PNG già trasparenti) oppure Wikimedia
  Commons (solo licenze libere, con autore e licenza);
- scontorno in locale sul processore, gratis e senza account, due qualità: «rapida» (ISNet,
  ~2 s) e «massima» (BiRefNet leggero, ~20 s, capelli e bordi molto più puliti). I modelli
  (~180 e ~220 MB) si scaricano la prima volta che servono in library/models/;
- l'originale resta in work/images/src/: si può rifare lo scontorno o usare la foto intera;
- i file finiscono in work/images/ del progetto (fuori da git, come tutto projects/).

Le immagini del web hanno quasi sempre un copyright: va bene per i video tuoi, ma decidi tu
cosa pubblicare. Le immagini le mette solo l'utente: Claude non le inserisce in automatico.
"""

from __future__ import annotations

import html
import io
import json
import re
import ssl
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import truststore

from .paths import REPO_ROOT

MODELS_DIR = REPO_ROOT / "library" / "models"
_RELEASE = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
# stessi modelli e stessa preparazione dell'immagine di rembg (MIT / Apache-2.0)
MODELS: dict[str, dict[str, Any]] = {
    "fast": {
        "file": "isnet-general-use.onnx", "url": _RELEASE + "isnet-general-use.onnx",
        "size": 178_648_008, "mean": (0.5, 0.5, 0.5), "std": (1.0, 1.0, 1.0), "sigmoid": False,
    },
    "best": {
        "file": "BiRefNet-general-lite.onnx",
        "url": _RELEASE + "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "size": 224_005_088, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225),
        "sigmoid": True,
    },
}  # fmt: skip
QUALITIES = tuple(MODELS)
IMAGES_DIR = "images"  # dentro work/
MAX_BYTES = 25 * 1024 * 1024
MAX_SIDE = 1600  # lato massimo dell'immagine salvata (basta per un 1080x1920)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
# Wikimedia vuole nome del programma e un contatto (il repository), altrimenti risponde 403
COMMONS_UA = (
    "autocut-editor/0.1 (https://github.com/federicobatildi46-ctrl/autocut; editor locale) httpx"
)

Progress = Callable[[str, float | None], None]  # (fase, 0..1 o None)


class ImageError(RuntimeError):
    pass


def _client(timeout: float = 20) -> httpx.Client:
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # certificati di sistema (antivirus)
    return httpx.Client(
        verify=ctx,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.6"},
    )


# --- ricerca ---------------------------------------------------------------------------

# Toglie solo la richiesta all'inizio («trovami delle foto di …»), mai pezzi del nome
# («Del Piero» resta Del Piero): verbo, articolo, «immagini/foto», «scontornate», «di».
_ASK = re.compile(
    r"^(?:(?:per favore|ciao|ehi|mi|puoi|potresti|cercami|cerca|cercare|cerchi|"
    r"trovami|trova|trovi|trovare|"
    r"dammi|fammi vedere|voglio|vorrei|mostrami|metti|aggiungi)\s+)*"
    r"(?:(?:delle|degli|dei|una|un'|un|qualche|le|la|il|lo|l')\s*)?"
    r"(?:immagin[ei]|foto(?:grafi[ae])?|pic|png)\s+"
    r"(?:(?:scontornat[aei]|senza sfondo|trasparent[ei]|belle?|sul web|online)\s+)*"
    r"(?:(?:di|del|della|dello|dei|degli|delle|con)\s+)?",
    re.IGNORECASE,
)
_VERB = re.compile(
    r"^(?:(?:per favore|cercami|cerca|trovami|trova|dammi|mostrami)\s+)+", re.IGNORECASE
)


def clean_query(text: str) -> str:
    """«trovami delle immagini di Francesco Totti» → «Francesco Totti»."""
    q = " ".join(text.replace("’", "'").split()).strip(" .?!")
    q2 = _ASK.sub("", q + " ").strip()
    if q2 == q:
        q2 = _VERB.sub("", q + " ").strip()
    return q2 or q


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def search_web(query: str, *, transparent: bool = False, count: int = 35) -> list[dict[str, Any]]:
    """Bing Immagini (la stessa ricerca del browser). transparent = solo PNG senza sfondo."""
    params: dict[str, Any] = {
        "q": query, "first": 0, "count": count, "mmasync": 1, "adlt": "moderate",
    }  # fmt: skip
    if transparent:
        params["qft"] = "+filterui:photo-transparent"
    with _client() as c:
        r = c.get("https://www.bing.com/images/async", params=params)
        r.raise_for_status()
    out = []
    for raw in re.findall(r'\sm="([^"]+)"', r.text):
        try:
            d = json.loads(html.unescape(raw))
        except ValueError:
            continue
        url, thumb = d.get("murl"), d.get("turl")
        if not url or not thumb or url.lower().endswith((".svg", ".gif")):
            continue
        out.append(
            {
                "url": url,
                "thumb": thumb,
                "page": d.get("purl") or "",
                "title": (d.get("t") or "").replace("", "").replace("", ""),
                "source": _domain(d.get("purl") or url),
                "license": None,
            }
        )
    return out


def search_free(query: str, *, count: int = 30) -> list[dict[str, Any]]:
    """Wikimedia Commons: solo foto con licenza libera (CC / pubblico dominio)."""
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": count, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": 360,
    }  # fmt: skip
    with _client() as c:
        r = c.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
            headers={"User-Agent": COMMONS_UA},
        )
        r.raise_for_status()
    pages = sorted((r.json().get("query") or {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 0))  # fmt: skip
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if not str(info.get("mime", "")).startswith(("image/jpeg", "image/png", "image/webp")):
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        out.append(
            {
                "url": info.get("url"),
                "thumb": info.get("thumburl") or info.get("url"),
                "page": info.get("descriptionurl") or "",
                "title": p.get("title", "").removeprefix("File:").rsplit(".", 1)[0],
                "source": "commons.wikimedia.org",
                "license": " · ".join(x for x in (lic, artist[:60]) if x) or None,
            }
        )
    return out


def search(query: str, *, transparent: bool = False, free: bool = False) -> list[dict[str, Any]]:
    q = clean_query(query)
    if not q:
        return []
    try:
        return search_free(q) if free else search_web(q, transparent=transparent)
    except httpx.HTTPError as exc:
        raise ImageError(f"ricerca non riuscita ({exc.__class__.__name__}): riprova") from exc


# --- download --------------------------------------------------------------------------


def _open_image(data: bytes):
    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # qualsiasi formato rotto o non immagine
        raise ImageError("il file scaricato non è un'immagine leggibile") from exc
    im = ImageOps.exif_transpose(im)
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P", "PA") else im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def fetch(url: str, *, referer: str = "", fallback: str | None = None) -> bytes:
    """Scarica l'immagine originale; se il sito la blocca usa la miniatura (più piccola)."""
    errors = []
    for u in [url, fallback] if fallback else [url]:
        if not u or urlparse(u).scheme not in ("http", "https"):
            continue
        try:
            with _client(timeout=30) as c:
                headers = {"Referer": referer} if referer else {}
                with c.stream("GET", u, headers=headers) as r:
                    r.raise_for_status()
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > MAX_BYTES:
                            raise ImageError("immagine troppo pesante (oltre 25 MB)")
            _open_image(bytes(buf))  # deve essere un'immagine vera
            return bytes(buf)
        except (httpx.HTTPError, ImageError) as exc:
            errors.append(str(exc))
    raise ImageError(f"non riesco a scaricare l'immagine: {errors[-1] if errors else 'url vuoto'}")


# --- scontorno -------------------------------------------------------------------------

_sessions: dict[str, Any] = {}
_session_lock = threading.Lock()


def model_path(quality: str) -> Path:
    return MODELS_DIR / MODELS[quality]["file"]


def ensure_model(quality: str = "fast", progress: Progress | None = None) -> Path:
    """Scarica una volta sola il modello (con avanzamento)."""
    spec = MODELS[quality]
    path = model_path(quality)
    if path.is_file() and path.stat().st_size > 1_000_000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    try:
        with _client(timeout=60) as c, c.stream("GET", spec["url"]) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or spec["size"])
            done = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress("model", min(1.0, done / total))
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise ImageError(f"non riesco a scaricare il modello per scontornare: {exc}") from exc
    tmp.replace(path)
    return path


def _get_session(quality: str, progress: Progress | None):
    with _session_lock:
        if quality not in _sessions:
            import onnxruntime as ort

            model = ensure_model(quality, progress)
            if progress:
                progress("loading", None)
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            _sessions[quality] = ort.InferenceSession(
                str(model), sess_options=opts, providers=["CPUExecutionProvider"]
            )
        return _sessions[quality]


def _has_alpha(im) -> bool:
    """Già scontornata (PNG trasparente): almeno il 4% dei pixel è trasparente."""
    if im.mode != "RGBA":
        return False
    hist = im.getchannel("A").histogram()
    return sum(hist[:16]) > 0.04 * im.width * im.height


def mask_for(im, progress: Progress | None = None, quality: str = "fast"):
    """Maschera della figura in primo piano (L, stessa grandezza dell'immagine)."""
    import numpy as np
    from PIL import Image

    spec = MODELS[quality]
    sess = _get_session(quality, progress)
    if progress:
        progress("cutting", None)
    inp = sess.get_inputs()[0]
    side = inp.shape[-1] if isinstance(inp.shape[-1], int) else 1024
    rgb = im.convert("RGB").resize((side, side), Image.Resampling.BILINEAR)
    x = np.asarray(rgb, dtype=np.float32) / 255.0
    x = (x - np.array(spec["mean"], dtype=np.float32)) / np.array(spec["std"], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    pred = sess.run(None, {inp.name: x})[0][0, 0]
    if spec["sigmoid"]:
        pred = 1.0 / (1.0 + np.exp(-pred))
    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / max(hi - lo, 1e-6)
    pred = np.clip((pred - 0.03) / 0.94, 0, 1)  # bordi puliti, niente alone grigio
    m = Image.fromarray((pred * 255).astype(np.uint8), mode="L")
    return m.resize(im.size, Image.Resampling.LANCZOS)


def _trim(im, pad: float = 0.02):
    """Taglia il trasparente intorno alla figura (con un filo di margine)."""
    box = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if not box:
        raise ImageError("non ho trovato nessuna figura da scontornare in questa immagine")
    x0, y0, x1, y1 = box
    p = round(max(x1 - x0, y1 - y0) * pad)
    return im.crop((max(0, x0 - p), max(0, y0 - p), min(im.width, x1 + p), min(im.height, y1 + p)))


def prepare(
    data: bytes,
    dest: Path,
    *,
    cutout: bool = True,
    quality: str = "fast",
    progress: Progress | None = None,
    masker: Callable[..., Any] = mask_for,
) -> dict[str, Any]:
    """Salva l'immagine in dest (PNG). cutout = toglie lo sfondo e taglia intorno alla figura;
    l'originale va in src/ accanto, per rifare lo scontorno."""
    if quality not in MODELS:
        raise ImageError(f"qualità {quality!r} sconosciuta")
    im = _open_image(data)
    src = dest.parent / "src" / dest.name
    src.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists() or src.read_bytes() != data:
        im.save(src, "PNG")
    already = _has_alpha(im)
    if cutout and not already:
        im = im.convert("RGBA")
        im.putalpha(masker(im, progress, quality))
    if cutout or already:
        im = _trim(im.convert("RGBA"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial.png")
    im.save(tmp, "PNG", optimize=False)
    tmp.replace(dest)
    return {
        "width": im.width,
        "height": im.height,
        "cutout": bool(cutout or already),
        "quality": quality if cutout and not already else None,
    }


def original(dest: Path) -> bytes:
    """L'immagine com'era prima dello scontorno (per rifarlo)."""
    src = dest.parent / "src" / dest.name
    if not src.is_file():
        raise ImageError("l'originale di questa immagine non c'è più")
    return src.read_bytes()


def next_name(folder: Path) -> str:
    nums = [
        int(m.group(1))
        for p in (folder.glob("img_*.png") if folder.is_dir() else [])
        if (m := re.fullmatch(r"img_(\d+)\.png", p.name))
    ]
    return f"img_{(max(nums) + 1 if nums else 1):04d}.png"


def library(work: Path) -> list[dict[str, Any]]:
    """Immagini già preparate in questo progetto (le più recenti prima)."""
    folder = work / IMAGES_DIR
    if not folder.is_dir():
        return []
    meta = _read_meta(folder)
    files = sorted(folder.glob("img_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "image": f"{IMAGES_DIR}/{p.name}",
            "url": f"/media/images/{p.name}?v={int(p.stat().st_mtime)}",
            **meta.get(p.name, {}),
        }
        for p in files
    ]


def _read_meta(folder: Path) -> dict[str, Any]:
    p = folder / "index.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def remember(folder: Path, name: str, info: dict[str, Any]) -> None:
    """Da dove viene ogni immagine (titolo, sito, licenza): in work/images/index.json."""
    meta = _read_meta(folder)
    meta[name] = info
    tmp = folder / "index.partial"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(folder / "index.json")
