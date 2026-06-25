#!/usr/bin/env python3
"""Normalize the OpenType GDEF table version after export."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")
GDEF_VERSION_1_0 = 0x00010000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set the GDEF table version to 1.0. Some exports can write GDEF "
            "with version 0, which OTS rejects as `GDEF: Bad version` and "
            "FontBakery reports as ots/ttx_roundtrip failures."
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
            "Missing dependency: fontTools. Install project requirements first."
        ) from error

    font = TTFont(font_path)

    if "GDEF" not in font:
        print(f"No GDEF table found in {font_path}")
        return 0

    current_version = getattr(font["GDEF"].table, "Version", None)
    if current_version == GDEF_VERSION_1_0:
        print(f"GDEF version already 0x{GDEF_VERSION_1_0:08X} in {font_path}")
        return 0

    font["GDEF"].table.Version = GDEF_VERSION_1_0
    font.save(output_path)

    print(
        f"Changed GDEF version from 0x{int(current_version or 0):08X} "
        f"to 0x{GDEF_VERSION_1_0:08X} in {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
