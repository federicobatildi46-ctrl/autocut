"""Libreria SFX senza chiamare ElevenLabs (trasporto finto) e senza ffmpeg (analisi finta)."""

import json
from array import array

import httpx
import pytest

from autocut.sound.library import (
    API_URL,
    SfxError,
    analyze_samples,
    build_catalog,
    estimate_credits,
    file_for,
    generate_library,
)
from autocut.sound.manifest import FAMILIES, MANIFEST, by_id, total_files, total_seconds

# Tutto ciò che il documento master nomina nelle sezioni A2 (whoosh, texture, riser/hit).
REQUIRED = {
    "whoosh.classy_airy", "whoosh.hollow", "whoosh.futuristic", "whoosh.deep_voice",
    "whoosh.generic_long", "whoosh.organic_wind", "whoosh.short", "whoosh.synthetic",
    "whoosh.transition_spacey", "whoosh.water_dropper",
    "texture.pop", "texture.ui_click", "texture.scifi_click", "texture.gears",
    "texture.tiny_gearwheel", "texture.keyboard_writing", "texture.analog_button",
    "texture.video_scan", "texture.scifi_impact", "texture.activate_protection_energy",
    "texture.digital_camera_click", "texture.heavenly_choir", "texture.success_reward",
    "texture.alarm_buzzer", "texture.scifi_hit",
    "riser.sharp_bass", "riser.metallic", "riser.suspenseful", "riser.suck_back", "hit.impact",
}  # fmt: skip


def test_manifest_covers_the_master_document():
    assert set(by_id()) == REQUIRED
    assert len(by_id()) == len(MANIFEST)  # id unici


def test_manifest_rules():
    for s in MANIFEST:
        assert s.family in FAMILIES
        assert 0.5 <= s.duration_s <= 30  # limiti dell'API
        assert s.variations >= 1
        assert "no music" in s.prompt  # mai musica
    riser_vars = {s.id: s.variations for s in MANIFEST if s.family == "risers"}
    assert riser_vars["riser.sharp_bass"] >= 2 and riser_vars["riser.metallic"] >= 2
    levels = {s.family: s.level_db for s in MANIFEST}
    assert levels["whooshes"] == -12 and levels["risers"] == -5


def test_totals_and_cost():
    assert total_files() == 71
    assert estimate_credits(MANIFEST) == round(total_seconds() * 40)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generate_writes_files_sidecars_and_skips_existing(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        assert str(request.url).startswith(API_URL)
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "k"
        return httpx.Response(200, content=b"ID3fake")

    specs = (by_id()["texture.pop"],)
    r = generate_library(specs, api_key="k", root=tmp_path, client=_client(handler))
    assert r.generated == ["texture.pop.01", "texture.pop.02", "texture.pop.03"]
    assert len(calls) == 3  # una generazione per chiamata
    assert calls[0]["duration_seconds"] == 0.5 and calls[0]["model_id"] == "eleven_text_to_sound_v2"
    f = file_for(tmp_path, specs[0], 1)
    assert f.read_bytes() == b"ID3fake"
    assert json.loads(f.with_suffix(".json").read_text())["type"] == "texture.pop"

    again = generate_library(specs, api_key="k", root=tmp_path, client=_client(handler))
    assert again.generated == [] and len(again.skipped) == 3 and len(calls) == 3


def test_auth_error_stops_early(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"detail": "missing permission"})

    r = generate_library(MANIFEST[:3], api_key="k", root=tmp_path, client=_client(handler))
    assert len(calls) == 1 and "rifiutato la chiave" in r.failed[0][1]


def test_retry_on_rate_limit(tmp_path):
    seq = [429, 200]

    def handler(request):
        return httpx.Response(seq.pop(0), content=b"x")

    spec = by_id()["texture.alarm_buzzer"]
    r = generate_library(
        (spec,), api_key="k", root=tmp_path, client=_client(handler), sleep=lambda s: None
    )
    assert r.generated == ["texture.alarm_buzzer.01"]


def test_analyze_samples_finds_the_peak():
    rate = 1000
    s = array("h", [0] * 1000)
    s[700] = 16384
    a = analyze_samples(s, rate)
    assert a["duration_ms"] == 1000 and a["transient_ms"] == 700 and a["peak_dbfs"] == -6.0
    assert a["peak_ms"] == 725  # centro della finestra di 50 ms che contiene il picco
    assert len(a["envelope"]) == 20 and a["envelope"][14] == 100


def test_envelope_peak_follows_the_swell_not_the_click():
    rate = 1000
    s = array("h", [0] * 2000)
    s[10] = 30000  # click iniziale isolato
    for i in range(1500, 1800):
        s[i] = 8000 if i % 2 else -8000  # parte "gonfia" verso la fine (riser)
    a = analyze_samples(s, rate)
    assert a["transient_ms"] == 10
    assert 1500 <= a["peak_ms"] <= 1800


def test_catalog_reports_coverage(tmp_path):
    pop = by_id()["texture.pop"]
    for n in (1, 2):
        p = file_for(tmp_path, pop, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    fake = lambda path: {"duration_ms": 500, "peak_ms": 40, "peak_dbfs": -3.0, "rms_dbfs": -20.0}  # noqa: E731
    cat = build_catalog(tmp_path, MANIFEST, analyzer=fake)
    assert [s["id"] for s in cat["sounds"]] == ["texture.pop.01", "texture.pop.02"]
    assert cat["sounds"][0]["level_db"] == -6.5 and cat["sounds"][0]["peak_ms"] == 40
    assert cat["coverage"]["texture.pop"] == {"found": 2, "expected": 3}
    assert "texture.pop" in cat["partial_types"]
    assert "riser.metallic" in cat["missing_types"]
    assert (tmp_path / "catalog.json").exists() and (tmp_path / "LICENZE.txt").exists()


def test_sfx_error_type():
    with pytest.raises(SfxError):
        raise SfxError("x")
