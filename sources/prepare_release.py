#!/usr/bin/env python3
"""Repeatably prepare the supplied exports; this is NOT a design-source build."""
from pathlib import Path
import hashlib
import json
import shutil

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "sources/release-inputs"
FAMILY = "Gothic Gumdrop"
PS_NAME = "GothicGumdrop-Regular"
COPYRIGHT = (
    "Copyright 2026 The Gothic Gumdrop Project Authors "
    "(https://github.com/mixfont/gothic-gumdrop). "
    "Copyright 2026 Mixfont (https://www.mixfont.com) and Type Innovations "
    "(https://www.typeinnovations.com/). All rights reserved."
)
LICENSE = (
    "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
    "This license is available with a FAQ at: https://openfontlicense.org"
)
DESCRIPTION = (
    "Gothic Gumdrop is a cute, bubbly blackletter display typeface. "
    "Initially generated with Mixfont by Eric Lu and refined in collaboration "
    "with Alex Kaczun of Type Innovations."
)


def prepare():
    source = INPUTS / "GothicGumDrop-Regular.ttf"
    manifest = json.loads((INPUTS / "provenance.json").read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["inputs"][source.name]:
        raise ValueError(f"Input checksum mismatch: {source}")
    font = TTFont(source, recalcTimestamp=False)
    names = {
        0: COPYRIGHT, 1: FAMILY, 2: "Regular", 3: f"1.100;NONE;{PS_NAME}",
        4: f"{FAMILY} Regular", 5: "Version 1.100", 6: PS_NAME,
        7: "Gothic Gumdrop is a trademark by Mixfont LLC and may be registered in certain jurisdictions.",
        8: "Mixfont LLC, Type Innovations Inc.", 9: "Eric Lu, Alex Kaczun",
        10: DESCRIPTION, 11: "https://www.mixfont.com", 12: "https://www.typeinnovations.com/",
        13: LICENSE, 14: "https://openfontlicense.org",
    }
    font["name"].names = []
    for name_id, value in names.items():
        font["name"].setName(value, name_id, 3, 1, 0x409)
    font["head"].fontRevision = 1.100
    # Fixed export timestamp makes repeat packaging byte-for-byte reproducible.
    font["head"].modified = 3874261185
    os2 = font["OS/2"]
    os2.fsType = 0
    os2.achVendID = "NONE"
    os2.fsSelection |= 1 << 7
    # Use the release metrics: 1245 units of line spacing.
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 935, -310, 0
    font["hhea"].ascent, font["hhea"].descent, font["hhea"].lineGap = 935, -310, 0
    os2.usWinAscent, os2.usWinDescent = 886, 250
    if "DSIG" in font:
        del font["DSIG"]
    font["meta"] = newTable("meta")
    font["meta"].data = {"dlng": "Latn", "slng": "Latn"}

    # Flatten reflected/scaled components, rounding to integer font units.
    # Do not simplify or redesign the contours.
    glyph_set = font.getGlyphSet()
    for name in font.getGlyphOrder():
        glyph = font["glyf"][name]
        if glyph.isComposite() and any(
            component.getComponentInfo()[1][:4] != (1, 0, 0, 1)
            for component in glyph.components
        ):
            recording = DecomposingRecordingPen(glyph_set)
            glyph_set[name].draw(recording)
            pen = TTGlyphPen(None)
            recording.replay(pen)
            font["glyf"][name] = pen.glyph()
    # Keep supplied hinting, adding the standard smart-dropout setup.
    prep = font["prep"].program
    prep.fromBytecode(prep.getBytecode() + b"\xb8\x01\xff\x85\xb0\x04\x8d")
    font["head"].flags |= 1 << 3
    output = ROOT / f"fonts/ttf/{PS_NAME}.ttf"
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output)


def main():
    prepare()
    package = ROOT / "build/googlefonts/ofl/gothicgumdrop"
    package.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / f"fonts/ttf/{PS_NAME}.ttf", package)
    for name in ("OFL.txt", "TRADEMARKS.md"):
        shutil.copy2(ROOT / name, package)
    for name in ("METADATA.pb", "DESCRIPTION.en_us.html"):
        shutil.copy2(ROOT / "documentation/googlefonts" / name, package)
    print(f"Prepared TTF and review package: {package}")
    print("Submission still requires a source-build workflow and design fixes.")


if __name__ == "__main__":
    main()
