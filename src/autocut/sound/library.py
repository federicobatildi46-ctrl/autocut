"""Libreria SFX: generazione con ElevenLabs Sound Effects e catalogo.

- Una generazione per chiamata (il documento master vieta le generazioni in batch).
- I file già presenti non si rigenerano (non si ripagano), salvo `force`.
- Accanto a ogni file c'è un `.json` con prompt, modello e data.
- `catalog.json` riassume tutto: id, famiglia, uso, livello, durata e **posizione del picco**
  (serve a mettere il picco del whoosh sul frame più veloce, o il transiente sull'evento).
"""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import time
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from math import log10
from pathlib import Path
from typing import Any

import httpx
import truststore

from ..paths import REPO_ROOT
from .manifest import MANIFEST, SfxSpec

API_URL = "https://api.elevenlabs.io/v1/sound-generation"
DEFAULT_MODEL = "eleven_text_to_sound_v2"
OUTPUT_FORMAT = "mp3_44100_128"
PROMPT_INFLUENCE = 0.45
CREDITS_PER_SECOND = 40  # tariffa dichiarata da ElevenLabs con durata fissata
LIBRARY_DIR = REPO_ROOT / "library" / "sfx"
CATALOG_FILE = "catalog.json"
ANALYSIS_RATE = 22050
RETRY_STATUS = {429, 500, 502, 503, 504}


class SfxError(RuntimeError):
    pass


def file_for(root: Path, spec: SfxSpec, n: int) -> Path:
    return root / spec.family / spec.folder / f"{spec.folder}_{n:02d}.mp3"


def estimate_credits(specs: Iterable[SfxSpec]) -> int:
    return round(sum(s.duration_s * s.variations for s in specs) * CREDITS_PER_SECOND)


def make_client() -> httpx.Client:
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(verify=ctx, timeout=httpx.Timeout(180.0, connect=30.0))


def generate_one(
    spec: SfxSpec,
    *,
    api_key: str,
    client: httpx.Client,
    model: str = DEFAULT_MODEL,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    body = {
        "text": spec.prompt,
        "duration_seconds": spec.duration_s,
        "prompt_influence": PROMPT_INFLUENCE,
        "model_id": model,
    }
    for attempt in range(retries + 1):
        try:
            resp = client.post(
                API_URL,
                params={"output_format": OUTPUT_FORMAT},
                headers={"xi-api-key": api_key},
                json=body,
            )
        except httpx.TransportError as exc:
            if attempt < retries:
                sleep(3.0 * (attempt + 1))
                continue
            raise SfxError(f"connessione a ElevenLabs fallita: {exc}") from exc
        if resp.status_code == 200 and resp.content:
            return resp.content
        if resp.status_code in RETRY_STATUS and attempt < retries:
            sleep(3.0 * (attempt + 1))
            continue
        detail = resp.text[:300]
        if resp.status_code in (401, 403):
            raise SfxError(f"ElevenLabs ha rifiutato la chiave ({resp.status_code}): {detail}")
        raise SfxError(f"ElevenLabs ha risposto {resp.status_code}: {detail}")
    raise SfxError("tentativi esauriti")  # pragma: no cover


@dataclass
class GenerateReport:
    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def credits(self) -> int:
        return round(self.seconds * CREDITS_PER_SECOND)


def generate_library(
    specs: Iterable[SfxSpec] = MANIFEST,
    *,
    api_key: str,
    root: Path = LIBRARY_DIR,
    client: httpx.Client | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    stop_on_auth_error: bool = True,
    log: Callable[[str], None] = lambda s: None,
    sleep: Callable[[float], None] = time.sleep,
) -> GenerateReport:
    report = GenerateReport()
    own = client is None
    http = client or make_client()
    try:
        for spec in specs:
            for n in range(1, spec.variations + 1):
                path = file_for(root, spec, n)
                name = f"{spec.id}.{n:02d}"
                if path.exists() and not force:
                    report.skipped.append(name)
                    continue
                try:
                    audio = generate_one(
                        spec, api_key=api_key, client=http, model=model, sleep=sleep
                    )
                except SfxError as exc:
                    report.failed.append((name, str(exc)))
                    log(f"ERRORE {name}: {exc}")
                    if stop_on_auth_error and "rifiutato la chiave" in str(exc):
                        return report
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(audio)
                meta = {
                    "id": name,
                    "type": spec.id,
                    "prompt": spec.prompt,
                    "duration_s": spec.duration_s,
                    "model": model,
                    "output_format": OUTPUT_FORMAT,
                    "source": "ElevenLabs Sound Effects",
                    "created_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                }
                path.with_suffix(".json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                report.generated.append(name)
                report.seconds += spec.duration_s
                log(f"ok     {name}  ({spec.duration_s:.1f} s)")
    finally:
        if own:
            http.close()
    return report


# --- analisi e catalogo ---------------------------------------------------------------


def analyze(path: Path) -> dict[str, Any]:
    """Durata, posizione del picco e livelli (ffmpeg -> PCM mono)."""
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise SfxError("ffmpeg non trovato nel PATH")
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1",
         "-ar", str(ANALYSIS_RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise SfxError(f"{path.name}: {proc.stderr.decode('utf-8', 'replace')[-200:]}")
    raw = proc.stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    return analyze_samples(samples, ANALYSIS_RATE)


ENVELOPE_WINDOW_MS = 50


def analyze_samples(samples: array, rate: int) -> dict[str, Any]:
    """`peak_ms` = centro della finestra di 50 ms più forte (picco dell'inviluppo, quello da
    allineare al frame); `transient_ms` = campione più forte (per pop/click sull'evento)."""
    if not samples:
        return {
            "duration_ms": 0, "peak_ms": 0, "transient_ms": 0,
            "peak_dbfs": None, "rms_dbfs": None, "envelope": [],
        }  # fmt: skip
    peak_i, peak = 0, 0
    total = 0
    for i, s in enumerate(samples):
        a = -s if s < 0 else s
        total += s * s
        if a > peak:
            peak, peak_i = a, i
    rms = (total / len(samples)) ** 0.5

    win = max(1, rate * ENVELOPE_WINDOW_MS // 1000)
    envelope: list[float] = []
    for start in range(0, len(samples), win):
        chunk = samples[start : start + win]
        envelope.append((sum(s * s for s in chunk) / len(chunk)) ** 0.5)
    loudest = max(range(len(envelope)), key=envelope.__getitem__)
    env_center = min(len(samples), loudest * win + win // 2)

    def dbfs(v: float) -> float | None:
        return round(20 * log10(v / 32768), 1) if v > 0 else None

    top = max(envelope) or 1.0
    return {
        "duration_ms": round(len(samples) * 1000 / rate),
        "peak_ms": round(env_center * 1000 / rate),
        "transient_ms": round(peak_i * 1000 / rate),
        "peak_dbfs": dbfs(peak),
        "rms_dbfs": dbfs(rms),
        # inviluppo normalizzato 0-100 ogni 50 ms (per vedere la forma: riser che cresce, hit...)
        "envelope": [round(100 * e / top) for e in envelope],
    }


def build_catalog(
    root: Path = LIBRARY_DIR,
    specs: Iterable[SfxSpec] = MANIFEST,
    analyzer: Callable[[Path], dict[str, Any]] = analyze,
) -> dict[str, Any]:
    specs = tuple(specs)
    sounds: list[dict[str, Any]] = []
    coverage: dict[str, dict[str, int]] = {}
    for spec in specs:
        found = 0
        for n in range(1, spec.variations + 1):
            path = file_for(root, spec, n)
            if not path.exists():
                continue
            found += 1
            meta_path = path.with_suffix(".json")
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            sounds.append(
                {
                    "id": f"{spec.id}.{n:02d}",
                    "type": spec.id,
                    "family": spec.family,
                    "label": spec.label,
                    "usage": spec.usage,
                    "frequency": spec.frequency,
                    "file": path.relative_to(root).as_posix(),
                    "level_db": spec.level_db,
                    **analyzer(path),
                    "model": meta.get("model"),
                    "source": meta.get("source"),
                    "prompt": meta.get("prompt", spec.prompt),
                }
            )
        coverage[spec.id] = {"found": found, "expected": spec.variations}
    missing = [t for t, c in coverage.items() if c["found"] == 0]
    partial = [t for t, c in coverage.items() if 0 < c["found"] < c["expected"]]
    catalog = {
        "version": 1,
        "generated_by": "autocut sfx catalog",
        "levels_db": {"whooshes": -12, "textures": -6.5, "risers": -5, "hits": -8, "music": -19},
        "sounds": sounds,
        "coverage": coverage,
        "missing_types": missing,
        "partial_types": partial,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / CATALOG_FILE).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "LICENZE.txt").write_text(
        "Suoni generati con ElevenLabs Sound Effects (API) da autocut.\n"
        "Uso commerciale: consentito con un piano ElevenLabs a pagamento; con il piano gratuito\n"
        "ElevenLabs richiede l'attribuzione (elevenlabs.io). Verifica i termini del tuo piano.\n"
        "Prompt, modello e data di ogni file sono nel .json accanto al file.\n",
        encoding="utf-8",
    )
    return catalog
