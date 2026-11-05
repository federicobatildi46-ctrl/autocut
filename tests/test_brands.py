import json
import shutil
from pathlib import Path

import pytest

from autocut.brands import BRANDS_DIR, BrandError, BrandPack, list_brands, load_brand
from autocut.editor.agent import FrameContext, generate_prompt, suggest_prompt


def _federico() -> dict:
    return json.loads((BRANDS_DIR / "federico" / "brand.json").read_text(encoding="utf-8"))


def test_repo_brand_packs_are_valid():
    ids = [b.id for b in list_brands()]
    assert ids == ["editoriale-chiaro", "federico"]


def test_google_fonts_url():
    b = load_brand(BRANDS_DIR / "federico" / "brand.json")
    url = b.google_fonts_url()
    assert url.startswith("https://fonts.googleapis.com/css2?")
    assert "family=Inter:wght@400;600;800" in url
    assert "family=Instrument+Serif:ital,wght@0,400;1,400" in url
    assert url.endswith("&display=swap")


def test_summary_for_ai_mentions_palette_fonts_and_style():
    s = BrandPack.model_validate(_federico()).summary_for_ai()
    assert "#2f6bff" in s and "Instrument Serif" in s and "glassmorphism" in s


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d["captions"]["vertical"].update(font="nope"), "font 'nope'"),
        (lambda d: d["captions"]["vertical"]["emphasis"].update(color="viola"), "colore 'viola'"),
        (lambda d: d["palette"].update(accent="blue"), "accent"),
        (lambda d: d["transitions"].update(default="boh"), "default"),
        (lambda d: d["transitions"]["presets"].append(d["transitions"]["presets"][0]), "duplicati"),
        (lambda d: d.update(id="Con Spazi"), "id"),
    ],
)
def test_invalid_brand_packs(mutate, match):
    data = _federico()
    mutate(data)
    with pytest.raises(ValueError, match=match):
        BrandPack.model_validate(data)


def test_folder_must_match_id(tmp_path):
    folder = tmp_path / "altro"
    folder.mkdir()
    shutil.copy(BRANDS_DIR / "federico" / "brand.json", folder / "brand.json")
    with pytest.raises(BrandError, match="diverso dalla cartella"):
        list_brands(tmp_path)


def test_brand_reaches_claude_prompts():
    ctx = FrameContext(
        frame_path=Path("f.jpg"),
        time_ms=0,
        rel_ms=0,
        portrait=True,
        transcript="ciao",
        project="p",
        brand="Brand «X». Palette: accento #2f6bff",
    )
    assert "Brand pack da rispettare" in suggest_prompt(ctx)
    assert "#2f6bff" in generate_prompt(ctx, "image", "x", 6)
    plain = FrameContext(**{**ctx.__dict__, "brand": ""})
    assert "Brand pack" not in suggest_prompt(plain)
