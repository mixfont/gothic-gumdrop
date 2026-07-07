#!/usr/bin/env python3
"""Render a side-by-side preview sheet comparing two builds of the font.

Text is shaped with HarfBuzz (so GPOS kerning applies) and rasterized with
FreeType, exactly like a browser would render the font.

Usage:
  make_preview_sheet.py --before old.ttf --after new.ttf -o preview.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import freetype
import uharfbuzz as hb
from PIL import Image, ImageDraw

MARGIN = 48
LABEL_COLOR = (120, 120, 120)
BEFORE_COLOR = (0, 0, 0)
AFTER_COLOR = (0, 0, 0)

SECTIONS = [
    ("Uppercase", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", 56),
    ("Lowercase", "abcdefghijklmnopqrstuvwxyz", 56),
    ("Digits & symbols", "0123456789 !?&@$%()[]#*", 56),
    ("Pangram", "Sphinx of black quartz, judge my vow.", 64),
    ("Pangram small", "The quick brown fox jumps over the lazy dog.", 34),
    ("Spacing", "nnonoo nnunuu llilii mimmim ooeoce", 56),
    ("Kerning", "AV AW Ta Te To Tr Ty LT LV LY PA VA WA Ye Yo", 56),
    ("Words", "Gothic Gumdrop Bubbly Blackletter Quality", 64),
    ("Accents", "ÀÉÎÕÜ åéîõü Çç ŠŽ Čň", 56),
]


def shape_line(font_path: str, text: str, size_px: int):
    """Return (glyph_id, x_px, y_px) placements and total advance, via HarfBuzz."""
    blob = hb.Blob.from_file_path(font_path)
    face = hb.Face(blob)
    font = hb.Font(face)
    upem = face.upem
    font.scale = (upem, upem)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    scale = size_px / upem
    placements = []
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        placements.append((info.codepoint,
                           (x + pos.x_offset) * scale,
                           pos.y_offset * scale))
        x += pos.x_advance
    return placements, x * scale


def render_line(ft_face, font_path: str, text: str, size_px: int,
                canvas: Image.Image, origin: tuple[int, int], color) -> int:
    """Draw one shaped line onto canvas; returns the right edge in px."""
    placements, width = shape_line(font_path, text, size_px)
    ft_face.set_pixel_sizes(0, size_px)
    ox, oy = origin
    for gid, dx, dy in placements:
        ft_face.load_glyph(gid, freetype.FT_LOAD_RENDER)
        bmp = ft_face.glyph.bitmap
        if bmp.width == 0:
            continue
        glyph_img = Image.frombytes("L", (bmp.width, bmp.rows), bytes(bmp.buffer))
        px = int(round(ox + dx + ft_face.glyph.bitmap_left))
        py = int(round(oy - dy - ft_face.glyph.bitmap_top))
        solid = Image.new("RGB", glyph_img.size, color)
        canvas.paste(solid, (px, py), glyph_img)
    return int(ox + width)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--before-label", default="BEFORE (original)")
    parser.add_argument("--after-label", default="AFTER (improved)")
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()

    face_before = freetype.Face(str(args.before))
    face_after = freetype.Face(str(args.after))

    # Estimate canvas height: per section, label + 2 lines + gaps.
    width = 2200
    y = MARGIN
    heights = []
    for _, _, size in SECTIONS:
        line_h = int(size * 1.45)
        heights.append(22 + 2 * line_h + 26)
    height = MARGIN * 2 + sum(heights)

    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    for (label, text, size), block_h in zip(SECTIONS, heights):
        line_h = int(size * 1.45)
        d.text((MARGIN, y), f"{label}  —  top: {args.before_label}, "
                            f"bottom: {args.after_label}", fill=LABEL_COLOR)
        baseline1 = y + 22 + int(line_h * 0.78)
        baseline2 = baseline1 + line_h
        render_line(face_before, str(args.before), text, size, img,
                    (MARGIN, baseline1), BEFORE_COLOR)
        render_line(face_after, str(args.after), text, size, img,
                    (MARGIN, baseline2), AFTER_COLOR)
        y += block_h

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
