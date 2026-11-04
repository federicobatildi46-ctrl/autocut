"""Client minimo per ElevenLabs Speech-to-Text (Scribe).

POST https://api.elevenlabs.io/v1/speech-to-text, multipart, header `xi-api-key`.
temperature=0 e seed fisso per risultati il più possibile ripetibili.
"""

from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import truststore

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
RETRY_STATUS = {429, 500, 502, 503, 504}


class ScribeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScribeRequest:
    model_id: str
    language_code: str
    timestamps_granularity: str = "word"
    tag_audio_events: bool = True  # sempre richiesti; cosa farne lo decide il passo dei tagli
    diarize: bool = False
    temperature: float = 0.0
    seed: int = 0

    def params(self) -> dict[str, Any]:
        return asdict(self)

    def form(self) -> dict[str, str]:
        out = {}
        for key, value in asdict(self).items():
            out[key] = ("true" if value else "false") if isinstance(value, bool) else str(value)
        return out


def make_client() -> httpx.Client:
    """Certificati di sistema (truststore): funziona anche dietro antivirus/proxy che
    intercettano il TLS."""
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(verify=ctx, timeout=httpx.Timeout(600.0, connect=30.0))


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return str(detail)[:300]


def transcribe_file(
    path: Path,
    request: ScribeRequest,
    *,
    api_key: str,
    client: httpx.Client | None = None,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    own_client = client is None
    http = client or make_client()
    try:
        for attempt in range(retries + 1):
            try:
                with path.open("rb") as fh:
                    resp = http.post(
                        API_URL,
                        headers={"xi-api-key": api_key},
                        data=request.form(),
                        files={"file": (path.name, fh, "audio/flac")},
                    )
            except httpx.TransportError as exc:
                if attempt < retries:
                    sleep(2.0 * (attempt + 1))
                    continue
                raise ScribeError(f"connessione a ElevenLabs fallita: {exc}") from exc

            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, dict) or "words" not in data:
                    raise ScribeError("risposta di Scribe senza 'words'")
                return data
            if resp.status_code in RETRY_STATUS and attempt < retries:
                sleep(2.0 * (attempt + 1))
                continue
            if resp.status_code in (401, 403):
                raise ScribeError(
                    f"ElevenLabs ha rifiutato la chiave ({resp.status_code}): {_error_detail(resp)}"
                )
            raise ScribeError(f"ElevenLabs ha risposto {resp.status_code}: {_error_detail(resp)}")
        raise ScribeError("tentativi esauriti")  # pragma: no cover
    finally:
        if own_client:
            http.close()
