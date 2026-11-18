"""Estrae le emoji di un font a bitmap (CBDT) come PNG + indice per categorie.

uso (ambiente separato, fontTools non è una dipendenza del progetto):
    uv run --system-certs --no-project --python 3.12 --with fonttools python -I
        tools/extract_emoji.py AppleColorEmoji-Linux.ttf emoji.json library/emoji
    (tutto su una riga)

font:  github.com/samuelngs/apple-emoji-ttf (release, AppleColorEmoji-Linux.ttf, 96 px)
elenco: cdn.jsdelivr.net/npm/emoji-datasource@16.0.0/emoji.json (categorie della tastiera)
Le emoji sono disegni di Apple: solo uso personale, mai in git, non per i video dei clienti.
"""

import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

font_path, meta_path, out_dir = sys.argv[1:4]
out = Path(out_dir)
(out / "apple").mkdir(parents=True, exist_ok=True)

font = TTFont(font_path, lazy=True)
names = set(font.getGlyphOrder())

cbdt = font["CBDT"]
strikes = cbdt.strikeData
cblc = font["CBLC"]
ppems = [s.bitmapSizeTable.ppemX for s in cblc.strikes]
best = max(range(len(ppems)), key=lambda i: ppems[i])
glyphs = strikes[best]
print("strike ppem", ppems[best], "glifi", len(glyphs))


def glyph_for(cps: list[int]) -> str | None:
    """Nomi dei glifi nel font Apple: u1F525, u1F1EE_u1F1F9 (bandiere/ZWJ), .M/.W (uomo/donna)."""
    core = [c for c in cps if c not in (0xFE0F, 0x200D)]
    cands = ["_".join(f"u{c:04X}" for c in core)]
    if len(core) >= 2 and core[-1] in (0x2642, 0x2640):
        g = "M" if core[-1] == 0x2642 else "W"
        base = "_".join(f"u{c:04X}" for c in core[:-1])
        cands += [f"{base}.{g}", f"{base}.0.{g}"]
    if core and core[-1] == 0x27A1:  # "verso destra"
        base = "_".join(f"u{c:04X}" for c in core[:-1])
        cands += [f"{base}.u27A1", f"{base}.0.u27A1"]
    return next((c for c in cands if c in names), None)


meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
cats: dict[str, list] = {}
done = missing = 0
for e in sorted(meta, key=lambda x: x["sort_order"]):
    if e["category"] == "Component":
        continue
    cps = [int(x, 16) for x in e["unified"].split("-")]
    g = glyph_for(cps)
    bmp = glyphs.get(g) if g else None
    if bmp is None:
        missing += 1
        continue
    bmp.decompile() if hasattr(bmp, "decompile") and not hasattr(bmp, "imageData") else None
    data = getattr(bmp, "imageData", None)
    if not data or not data.startswith(b"\x89PNG"):
        missing += 1
        continue
    name = e["image"]  # es. 1f525.png, 1f1ee-1f1f9.png
    (out / "apple" / name).write_bytes(data)
    char = "".join(chr(c) for c in cps)
    cats.setdefault(e["category"], []).append(
        {"e": char, "img": name, "name": (e.get("short_name") or "").replace("_", " ")}
    )
    done += 1

index = {
    "source": "Apple Color Emoji (iOS) da github.com/samuelngs/apple-emoji-ttf",
    "ppem": ppems[best],
    "categories": [{"name": k, "items": v} for k, v in cats.items()],
}
(out / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
print("estratte", done, "mancanti", missing)
