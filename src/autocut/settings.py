"""Risoluzione delle impostazioni effettive.

Livelli, dal più debole al più forte:
  profiles.toml [defaults] -> profiles.toml [<profilo>] -> projects/<nome>/settings.json -> --set
Il risultato (un `Settings`) viene scritto tale e quale nel timeline.json.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models.timeline import Settings

PROFILES_PATH = Path(__file__).resolve().parents[2] / "profiles.toml"

ORIENTATION_PROFILE = {"landscape": "long", "portrait": "short", "square": "short"}


class SettingsError(ValueError):
    pass


def load_profiles(path: Path | None = None) -> dict[str, Any]:
    with (path or PROFILES_PATH).open("rb") as fh:
        return tomllib.load(fh)


def profile_names(profiles: Mapping[str, Any]) -> list[str]:
    return sorted(k for k in profiles if k != "defaults")


def profile_for_orientation(orientation: str) -> str:
    """Profilo di default quando non è indicato: orizzontale -> long, verticale -> short."""
    try:
        return ORIENTATION_PROFILE[orientation]
    except KeyError:
        raise SettingsError(f"orientamento sconosciuto: {orientation!r}") from None


def deep_merge(base: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def parse_set(expr: str) -> dict[str, Any]:
    """`pauses.threshold_ms=900` -> {"pauses": {"threshold_ms": 900}}.

    Il valore è interpretato come JSON se possibile, altrimenti resta stringa.
    """
    key, sep, raw = expr.partition("=")
    key = key.strip()
    if not sep or not key:
        raise SettingsError(f"--set non valido (atteso chiave=valore): {expr!r}")
    try:
        value: Any = json.loads(raw)
    except ValueError:
        value = raw
    parts = key.split(".")
    if any(not p for p in parts):
        raise SettingsError(f"--set: chiave non valida: {key!r}")
    nested: dict[str, Any] = {parts[-1]: value}
    for part in reversed(parts[:-1]):
        nested = {part: nested}
    return nested


def _reject_unknown(model: BaseModel, path: str = "") -> None:
    """I modelli ammettono campi extra (estendibilità); qui un refuso deve essere un errore."""
    if model.model_extra:
        names = ", ".join(f"{path}{k}" for k in sorted(model.model_extra))
        raise SettingsError(f"impostazioni sconosciute: {names}")
    for name in type(model).model_fields:
        child = getattr(model, name)
        if isinstance(child, BaseModel):
            _reject_unknown(child, f"{path}{name}.")


def resolve_settings(
    profile: str,
    *,
    profile_source: str = "cli",
    project_settings: Mapping[str, Any] | None = None,
    sets: Sequence[str] = (),
    profiles: Mapping[str, Any] | None = None,
) -> Settings:
    profiles = load_profiles() if profiles is None else profiles
    if profile not in profile_names(profiles):
        raise SettingsError(
            f"profilo sconosciuto {profile!r} (disponibili: {', '.join(profile_names(profiles))})"
        )
    merged = deep_merge(profiles.get("defaults", {}), profiles[profile])
    if project_settings:
        merged = deep_merge(merged, project_settings)
    for expr in sets:
        merged = deep_merge(merged, parse_set(expr))
    for fixed in ("profile", "profile_source"):
        if fixed in merged:
            raise SettingsError(f"{fixed!r} non si imposta qui: usa --profile")
    merged = {**merged, "profile": profile, "profile_source": profile_source}

    settings = Settings.model_validate(merged)
    _reject_unknown(settings)
    return settings


def apply_sets(settings: Settings, sets: Sequence[str], allowed: Sequence[str]) -> Settings:
    """Applica `--set` alle impostazioni già in timeline, solo sulle chiavi permesse da un passo
    (es. i tagli possono cambiare `pauses.*` ma non il modello di trascrizione)."""
    merged: dict[str, Any] = settings.model_dump(mode="json")
    for expr in sets:
        key = expr.partition("=")[0].strip()
        if not any(key == a or key.startswith(a + ".") for a in allowed):
            raise SettingsError(
                f"--set {key!r} non si può cambiare in questo passo (ammessi: {', '.join(allowed)})"
            )
        merged = deep_merge(merged, parse_set(expr))
    out = Settings.model_validate(merged)
    _reject_unknown(out)
    return out


def load_project_settings(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "settings.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: atteso un oggetto JSON")
    return data
