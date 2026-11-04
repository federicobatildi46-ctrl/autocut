"""Variabili d'ambiente e `.env` (escluso da git). Le chiavi non stanno mai nel codice."""

from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

API_KEY_VAR = "ELEVENLABS_API_KEY"


def load_env() -> None:
    """Carica `.env` dalla cartella corrente (o superiori) senza sovrascrivere l'ambiente."""
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


def api_key() -> str | None:
    load_env()
    value = os.environ.get(API_KEY_VAR, "").strip()
    return value or None
