#!/usr/bin/env python3
"""Remove the legacy OpenType DSIG table from a font file."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Strip the OpenType DSIG table. Google Fonts no longer expects "
            "DSIG in submitted fonts, and FontBakery reports it as "
            "opentype/dsig WARN [found-DSIG]."
        )
    )
    parser.add_argument(
        "font",
        nargs="?",
        type=Path,
        default=DEFAULT_FONT,
        help=f"Font file to edit. Defaults to {DEFAULT_FONT}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write to this path instead of modifying the input font in place.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    font_path = args.font
    output_path = args.output or font_path

    if not font_path.exists():
        raise SystemExit(f"Font file does not exist: {font_path}")

    try:
        from fontTools.ttLib import TTFont
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Run with "
            "`uv run --with fonttools python scripts/strip_dsig.py`."
        ) from error

    font = TTFont(font_path)

    if "DSIG" not in font:
        print(f"No DSIG table found in {font_path}")
        return 0

    del font["DSIG"]
    font.save(output_path)

    print(f"Removed DSIG table from {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
