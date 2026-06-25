#!/usr/bin/env python3
"""Run all TTF cleanup scripts for this project."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_FONT = REPO_ROOT / "fonts/ttf/GothicGumdrop-Regular.ttf"
CLEANUP_SCRIPTS = (
    "fix_mark_attachment.py",
    "fix_font_flags.py",
    "fix_gdef_version.py",
    "strip_name_ids.py",
    "strip_dsig.py",
)
OUTLINE_CLEANUP_SCRIPT = "cleanup_outlines.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all project TTF cleanup scripts on a font file."
    )
    parser.add_argument(
        "font",
        nargs="?",
        type=Path,
        default=DEFAULT_FONT,
        help="Font file to clean. Defaults to fonts/ttf/GothicGumdrop-Regular.ttf.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Clean a copied font at this path instead of editing the input in place.",
    )
    parser.add_argument(
        "--cleanup-outlines",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-outline-cleanup",
        action="store_true",
        help="Skip outline cleanup for FontBakery colinear/semi-vertical warnings.",
    )
    parser.add_argument(
        "--comparison-image",
        type=Path,
        help=(
            "Write a before/after PNG for glyphs edited by outline cleanup."
        ),
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_cleanup_script(script_name: str, font_path: Path) -> None:
    run_script(script_name, [str(font_path)])


def run_script(script_name: str, args: list[str]) -> None:
    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        raise SystemExit(f"Cleanup script does not exist: {display_path(script_path)}")

    print(f"Running {display_path(script_path)} {' '.join(args)}", flush=True)
    subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    args = parse_args()
    font_path = resolve_path(args.font)
    output_path = resolve_path(args.output) if args.output else font_path

    if not font_path.exists():
        raise SystemExit(f"Font file does not exist: {display_path(font_path)}")

    if args.output and output_path != font_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(font_path, output_path)
        print(f"Copied {display_path(font_path)} to {display_path(output_path)}", flush=True)

    if not args.skip_outline_cleanup:
        outline_args = [str(output_path)]
        if args.comparison_image:
            outline_args.extend(["--comparison-image", str(resolve_path(args.comparison_image))])
        run_script(OUTLINE_CLEANUP_SCRIPT, outline_args)

    for script_name in CLEANUP_SCRIPTS:
        run_cleanup_script(script_name, output_path)

    print(f"Cleanup complete: {display_path(output_path)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
