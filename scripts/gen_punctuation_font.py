#!/usr/bin/env python3
"""Builds gui/assets/fonts/NotoSansPunctuation.otf: the Latin-width ‘ ’ “ ” · … of Noto Sans CJK SC, the
glyphs its `locl` feature picks outside CJK text. The CJK font's own cmap draws these six full-width, so
the app puts this font ahead of it (gui/theme.py). Needs fonttools.

    ./.venv/bin/python scripts/gen_punctuation_font.py
"""

import pathlib

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gui" / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf"
OUT = ROOT / "gui" / "assets" / "fonts" / "NotoSansPunctuation.otf"
FAMILY = "Noto Sans Punctuation"
# Each character's proportional glyph, read off the font's GSUB `locl` (`pwid` for the ellipsis).
GLYPHS = {0x2018: "cid00725", 0x2019: "cid00726", 0x201C: "cid00728", 0x201D: "cid00729",
          0x00B7: "cid00733", 0x2026: "cid63163"}


def main() -> None:
    font = TTFont(SOURCE)
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(GLYPHS)
    options = subset.Options()
    options.layout_features = []
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=GLYPHS)
    subsetter.subset(font)
    for record in font["name"].names:
        if record.nameID in (1, 4, 16):
            record.string = FAMILY
        elif record.nameID == 6:
            record.string = FAMILY.replace(" ", "") + "-Regular"
    font["CFF "].cff.fontNames = [FAMILY.replace(" ", "") + "-Regular"]
    font.save(OUT)
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
