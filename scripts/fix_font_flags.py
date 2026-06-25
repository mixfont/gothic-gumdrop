#!/usr/bin/env python3
"""Normalize project-specific OpenType flags after TTF export."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")
HEAD_FORCE_INTEGER_PPEM = 1 << 3
OS2_USE_TYPO_METRICS = 1 << 7

# Keep the code page bits used by the checked-in font. A plain fontmake export
# currently writes only bits 0 and 1, which reopens FontBakery's code_pages check.
CODE_PAGE_RANGE_1 = 536871059
CODE_PAGE_RANGE_2 = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set FontBakery-required head and OS/2 flags on a TTF."
    )
    parser.add_argument(
        "font",
        nargs="?",
        type=Path,
        default=DEFAULT_FONT,
        help=f"Font file to edit. Defaults to {DEFAULT_FONT}.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.font.exists():
        raise SystemExit(f"Font file does not exist: {args.font}")

    try:
        from fontTools.ttLib import TTFont
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Install project requirements first."
        ) from error

    font = TTFont(args.font)
    changed: list[str] = []

    if "fpgm" in font and not font["head"].flags & HEAD_FORCE_INTEGER_PPEM:
        font["head"].flags |= HEAD_FORCE_INTEGER_PPEM
        changed.append("set head.flags bit 3")

    if not font["OS/2"].fsSelection & OS2_USE_TYPO_METRICS:
        font["OS/2"].fsSelection |= OS2_USE_TYPO_METRICS
        changed.append("set OS/2.fsSelection bit 7")

    if font["OS/2"].ulCodePageRange1 != CODE_PAGE_RANGE_1:
        font["OS/2"].ulCodePageRange1 = CODE_PAGE_RANGE_1
        changed.append("set OS/2.ulCodePageRange1")

    if font["OS/2"].ulCodePageRange2 != CODE_PAGE_RANGE_2:
        font["OS/2"].ulCodePageRange2 = CODE_PAGE_RANGE_2
        changed.append("set OS/2.ulCodePageRange2")

    if not changed:
        print(f"Font flags already normalized in {args.font}")
        return 0

    font.save(args.font)
    print(f"Updated {args.font}: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
