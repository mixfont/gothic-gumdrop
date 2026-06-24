#!/usr/bin/env python3
"""Remove selected OpenType name table records from a font file."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")
DEFAULT_NAME_IDS = (16, 17)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Strip OpenType name table records. By default this removes "
            "name IDs 16 and 17, which Google Fonts does not expect in a "
            "single-style family."
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
        "--name-id",
        dest="name_ids",
        action="append",
        type=int,
        default=[],
        help=(
            "Name ID to remove. May be passed multiple times. "
            "Defaults to 16 and 17 when omitted."
        ),
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
    name_ids = set(args.name_ids or DEFAULT_NAME_IDS)

    if not font_path.exists():
        raise SystemExit(f"Font file does not exist: {font_path}")

    try:
        from fontTools.ttLib import TTFont
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Run with "
            "`uv run --with fonttools python scripts/strip_name_ids.py`."
        ) from error

    font = TTFont(font_path)
    name_table = font["name"]
    original_records = list(name_table.names)
    kept_records = [record for record in original_records if record.nameID not in name_ids]
    removed_records = [record for record in original_records if record.nameID in name_ids]

    if not removed_records:
        print(f"No matching name IDs found in {font_path}: {sorted(name_ids)}")
        return 0

    name_table.names = kept_records
    font.save(output_path)

    removed = ", ".join(
        f"{record.nameID}={record.toUnicode()!r}" for record in removed_records
    )
    print(f"Removed {len(removed_records)} name record(s) from {output_path}: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
