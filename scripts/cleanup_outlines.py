#!/usr/bin/env python3
"""Conservatively clean simple TrueType outlines.

This targets two FontBakery outline warnings:

- outline_colinear_vectors: remove redundant on-curve points between two
  nearly colinear straight line segments.
- outline_semi_vertical: snap almost-horizontal or almost-vertical straight
  line segments when the required movement is very small.

Point deletion can invalidate TrueType hint bytecode. This script keeps hints
by default because that preserves the current Google Fonts smart-dropout checks
for this project, but it can drop hints with --drop-hints if validation shows
hint bytecode problems.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_FONT = Path("fonts/ttf/GothicGumdrop-Regular.ttf")
ON_CURVE = 0x01


@dataclass(frozen=True)
class Change:
    glyph: str
    message: str


@dataclass(frozen=True)
class GlyphSnapshot:
    name: str
    coords: tuple[tuple[float, float], ...]
    flags: tuple[int, ...]
    end_points: tuple[int, ...]


@dataclass(frozen=True)
class GlyphComparison:
    name: str
    before: GlyphSnapshot
    after: GlyphSnapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fix conservative colinear and semi-vertical outline issues."
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing a font.",
    )
    parser.add_argument(
        "--glyph",
        action="append",
        dest="glyphs",
        help="Only process this glyph name. Can be used multiple times.",
    )
    parser.add_argument(
        "--no-remove-colinear",
        action="store_true",
        help="Do not remove redundant colinear on-curve points.",
    )
    parser.add_argument(
        "--no-snap-semi",
        action="store_true",
        help="Do not snap nearly horizontal/vertical line segments.",
    )
    parser.add_argument(
        "--max-colinear-distance",
        type=float,
        default=1.5,
        help=(
            "Maximum point-to-chord distance, in font units, for deleting a "
            "nearly colinear point. Defaults to 1.5."
        ),
    )
    parser.add_argument(
        "--max-snap-units",
        type=int,
        default=2,
        help=(
            "Maximum coordinate movement, in font units, when snapping a "
            "near-horizontal/vertical segment. Defaults to 2."
        ),
    )
    parser.add_argument(
        "--semi-angle-tolerance",
        type=float,
        default=0.5,
        help="Angle tolerance in degrees for semi-horizontal/vertical lines.",
    )
    parser.add_argument(
        "--colinear-angle-tolerance",
        type=float,
        default=math.degrees(0.1),
        help="Angle tolerance in degrees for colinear vectors.",
    )
    parser.add_argument(
        "--drop-hints",
        action="store_true",
        help="Drop TrueType hints after point deletion.",
    )
    parser.add_argument(
        "--comparison-image",
        type=Path,
        help=(
            "Write a PNG showing before/after/overlay previews for every "
            "edited glyph. Works with --dry-run too."
        ),
    )
    return parser.parse_args()


def contour_ranges(end_points: list[int]) -> list[tuple[int, int]]:
    ranges = []
    start = 0
    for end in end_points:
        ranges.append((start, end))
        start = end + 1
    return ranges


def previous_index(start: int, end: int, index: int) -> int:
    return end if index == start else index - 1


def next_index(start: int, end: int, index: int) -> int:
    return start if index == end else index + 1


def is_on_curve(flags: list[int], index: int) -> bool:
    return bool(flags[index] & ON_CURVE)


def vector(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    return b[0] - a[0], b[1] - a[1]


def vector_length(v: tuple[int, int]) -> float:
    return math.hypot(v[0], v[1])


def vector_angle(v: tuple[int, int]) -> float:
    return math.degrees(math.atan2(v[1], v[0]))


def angle_delta(a: float, b: float) -> float:
    """Smallest absolute delta between two directed angles."""
    return abs((a - b + 180) % 360 - 180)


def point_line_distance(
    a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]
) -> float:
    """Distance from b to the line through a and c."""
    ac = vector(a, c)
    length = vector_length(ac)
    if length == 0:
        return math.inf
    return abs(ac[0] * (a[1] - b[1]) - (a[0] - b[0]) * ac[1]) / length


def delete_point(
    coords: list[tuple[int, int]], flags: list[int], end_points: list[int], index: int
) -> None:
    del coords[index]
    del flags[index]
    for i, end in enumerate(end_points):
        if end >= index:
            end_points[i] = end - 1


def remove_colinear_points(
    glyph_name: str,
    coords: list[tuple[int, int]],
    flags: list[int],
    end_points: list[int],
    max_distance: float,
    angle_tolerance: float,
) -> list[Change]:
    changes: list[Change] = []

    while True:
        deletion: tuple[int, str] | None = None
        for start, end in contour_ranges(end_points):
            point_count = end - start + 1
            if point_count <= 3:
                continue

            for index in range(start, end + 1):
                prev_i = previous_index(start, end, index)
                next_i = next_index(start, end, index)

                if not (
                    is_on_curve(flags, prev_i)
                    and is_on_curve(flags, index)
                    and is_on_curve(flags, next_i)
                ):
                    continue

                prev_v = vector(coords[prev_i], coords[index])
                next_v = vector(coords[index], coords[next_i])
                if vector_length(prev_v) == 0 or vector_length(next_v) == 0:
                    continue

                # Same direction, not a 180-degree reversal.
                if prev_v[0] * next_v[0] + prev_v[1] * next_v[1] <= 0:
                    continue

                delta = angle_delta(vector_angle(prev_v), vector_angle(next_v))
                distance = point_line_distance(coords[prev_i], coords[index], coords[next_i])
                if delta <= angle_tolerance and distance <= max_distance:
                    deletion = (
                        index,
                        (
                            f"removed point {coords[index]} between "
                            f"{coords[prev_i]} and {coords[next_i]} "
                            f"(angle delta {delta:.2f} deg, distance {distance:.2f})"
                        ),
                    )
                    break

            if deletion:
                break

        if not deletion:
            return changes

        index, message = deletion
        changes.append(Change(glyph_name, message))
        delete_point(coords, flags, end_points, index)


def nearest_axis(angle: float) -> tuple[str, float] | None:
    axes = [
        ("horizontal", -180.0),
        ("vertical", -90.0),
        ("horizontal", 0.0),
        ("vertical", 90.0),
        ("horizontal", 180.0),
    ]
    axis, expected = min(axes, key=lambda item: angle_delta(angle, item[1]))
    return axis, angle_delta(angle, expected)


def choose_snap_target(
    coords: list[tuple[int, int]],
    flags: list[int],
    start: int,
    end: int,
    first: int,
    second: int,
    axis_index: int,
) -> int:
    """Prefer the coordinate that already aligns with neighboring on-curve points."""
    candidates = [coords[first][axis_index], coords[second][axis_index]]
    scores = {}

    for candidate in candidates:
        score = 0
        for index in (
            previous_index(start, end, first),
            next_index(start, end, second),
        ):
            if is_on_curve(flags, index) and coords[index][axis_index] == candidate:
                score += 1
        scores[candidate] = score

    if scores[candidates[1]] > scores[candidates[0]]:
        return candidates[1]
    return candidates[0]


def set_axis(
    coords: list[tuple[int, int]], index: int, axis_index: int, value: int
) -> None:
    x, y = coords[index]
    coords[index] = (value, y) if axis_index == 0 else (x, value)


def snap_semi_vertical_lines(
    glyph_name: str,
    coords: list[tuple[int, int]],
    flags: list[int],
    end_points: list[int],
    max_snap_units: int,
    angle_tolerance: float,
) -> list[Change]:
    changes: list[Change] = []

    for start, end in contour_ranges(end_points):
        for first in range(start, end + 1):
            second = next_index(start, end, first)
            if not (is_on_curve(flags, first) and is_on_curve(flags, second)):
                continue

            x1, y1 = coords[first]
            x2, y2 = coords[second]
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0 or dy == 0:
                continue

            axis = nearest_axis(vector_angle((dx, dy)))
            if axis is None:
                continue
            axis_name, delta = axis
            if delta == 0 or delta > angle_tolerance:
                continue

            if axis_name == "vertical":
                if abs(dx) > max_snap_units:
                    continue
                target = choose_snap_target(coords, flags, start, end, first, second, 0)
                old_first, old_second = coords[first], coords[second]
                set_axis(coords, first, 0, target)
                set_axis(coords, second, 0, target)
                changes.append(
                    Change(
                        glyph_name,
                        f"snapped vertical segment {old_first}->{old_second} to x={target}",
                    )
                )
            else:
                if abs(dy) > max_snap_units:
                    continue
                target = choose_snap_target(coords, flags, start, end, first, second, 1)
                old_first, old_second = coords[first], coords[second]
                set_axis(coords, first, 1, target)
                set_axis(coords, second, 1, target)
                changes.append(
                    Change(
                        glyph_name,
                        f"snapped horizontal segment {old_first}->{old_second} to y={target}",
                    )
                )

    return changes


def clear_hints(font) -> None:
    from fontTools.ttLib.tables.ttProgram import Program

    for tag in ("cvt ", "fpgm", "prep", "hdmx", "VDMX", "LTSH"):
        if tag in font:
            del font[tag]

    if "glyf" in font:
        empty_program = Program()
        empty_program.fromBytecode([])
        for glyph in font["glyf"].glyphs.values():
            if hasattr(glyph, "program"):
                glyph.program = empty_program

    if "maxp" in font:
        maxp = font["maxp"]
        for attr in (
            "maxZones",
            "maxTwilightPoints",
            "maxStorage",
            "maxFunctionDefs",
            "maxInstructionDefs",
            "maxStackElements",
            "maxSizeOfInstructions",
        ):
            if hasattr(maxp, attr):
                setattr(maxp, attr, 0)


def selected_glyphs(glyph_order: Iterable[str], names: list[str] | None) -> set[str]:
    if names:
        return set(names)
    return set(glyph_order)


def make_snapshot(
    name: str,
    coords: Sequence[tuple[float, float]],
    flags: Sequence[int],
    end_points: Sequence[int],
) -> GlyphSnapshot:
    return GlyphSnapshot(
        name=name,
        coords=tuple((float(x), float(y)) for x, y in coords),
        flags=tuple(flags),
        end_points=tuple(end_points),
    )


def midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def quadratic_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1 - t
    return (
        mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
        mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
    )


def flatten_contour(
    points: Sequence[tuple[float, float]],
    flags: Sequence[int],
    steps: int = 16,
) -> list[tuple[float, float]]:
    if not points:
        return []

    count = len(points)
    on_curve = [bool(flag & ON_CURVE) for flag in flags]

    if on_curve[0]:
        start = points[0]
        index = 1
    elif on_curve[-1]:
        start = points[-1]
        index = 0
    else:
        start = midpoint(points[-1], points[0])
        index = 0

    flattened = [start]
    current = start
    consumed = 0

    while consumed < count:
        point = points[index]
        is_on = on_curve[index]
        next_index_ = (index + 1) % count

        if is_on:
            if point != current:
                flattened.append(point)
            current = point
            index = next_index_
            consumed += 1
            continue

        control = point
        next_point = points[next_index_]
        if on_curve[next_index_]:
            end_point = next_point
            advance = 2
        else:
            end_point = midpoint(control, next_point)
            advance = 1

        for step in range(1, steps + 1):
            flattened.append(quadratic_point(current, control, end_point, step / steps))

        current = end_point
        index = (index + advance) % count
        consumed += advance

    if flattened and flattened[0] != flattened[-1]:
        flattened.append(flattened[0])
    return flattened


def flattened_contours(snapshot: GlyphSnapshot) -> list[list[tuple[float, float]]]:
    contours = []
    start = 0
    for end in snapshot.end_points:
        points = snapshot.coords[start : end + 1]
        flags = snapshot.flags[start : end + 1]
        contour = flatten_contour(points, flags)
        if contour:
            contours.append(contour)
        start = end + 1
    return contours


def snapshot_bounds(snapshots: Sequence[GlyphSnapshot]) -> tuple[float, float, float, float]:
    xs = [x for snapshot in snapshots for x, _y in snapshot.coords]
    ys = [y for snapshot in snapshots for _x, y in snapshot.coords]
    if not xs or not ys:
        return 0, 0, 500, 700
    return min(xs), min(ys), max(xs), max(ys)


def draw_snapshot(
    draw,
    snapshot: GlyphSnapshot,
    bounds: tuple[float, float, float, float],
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    width: int = 2,
) -> None:
    min_x, min_y, max_x, max_y = bounds
    left, top, right, bottom = box
    glyph_width = max(max_x - min_x, 1)
    glyph_height = max(max_y - min_y, 1)
    padding = 22
    scale = min(
        (right - left - padding * 2) / glyph_width,
        (bottom - top - padding * 2) / glyph_height,
    )
    x_offset = left + (right - left - glyph_width * scale) / 2
    y_offset = top + (bottom - top + glyph_height * scale) / 2

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            x_offset + (x - min_x) * scale,
            y_offset - (y - min_y) * scale,
        )

    for contour in flattened_contours(snapshot):
        transformed = [transform(point) for point in contour]
        if len(transformed) >= 2:
            draw.line(transformed, fill=color, width=width, joint="curve")


def write_comparison_image(
    comparisons: Sequence[GlyphComparison],
    path: Path,
) -> None:
    if not comparisons:
        print(f"No edited glyphs; comparison image not written: {path}")
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: Pillow. Install project requirements first."
        ) from error

    row_height = 230
    label_width = 130
    panel_width = 220
    gap = 12
    margin = 18
    header_height = 46
    image_width = label_width + panel_width * 3 + gap * 2 + margin * 2
    image_height = header_height + row_height * len(comparisons) + margin

    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    headings = ["Glyph", "Before", "After", "Overlay"]
    draw.text((margin, 16), headings[0], fill=(20, 20, 20), font=font)
    x = margin + label_width
    for heading in headings[1:]:
        draw.text((x + 8, 16), heading, fill=(20, 20, 20), font=font)
        x += panel_width + gap

    for row, comparison in enumerate(comparisons):
        y = header_height + row * row_height
        row_bottom = y + row_height - 10
        draw.line((margin, y, image_width - margin, y), fill=(225, 225, 225))
        draw.text((margin, y + 16), comparison.name, fill=(20, 20, 20), font=font)

        bounds = snapshot_bounds([comparison.before, comparison.after])
        x = margin + label_width
        panels = [
            (comparison.before, (120, 120, 120)),
            (comparison.after, (0, 92, 180)),
        ]
        for snapshot, color in panels:
            box = (x, y + 18, x + panel_width, row_bottom)
            draw.rectangle(box, outline=(230, 230, 230))
            draw_snapshot(draw, snapshot, bounds, box, color)
            x += panel_width + gap

        overlay_box = (x, y + 18, x + panel_width, row_bottom)
        draw.rectangle(overlay_box, outline=(230, 230, 230))
        draw_snapshot(draw, comparison.before, bounds, overlay_box, (190, 190, 190))
        draw_snapshot(draw, comparison.after, bounds, overlay_box, (0, 92, 180))

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"Wrote comparison image: {path}")


def main() -> int:
    args = parse_args()

    if not args.font.exists():
        raise SystemExit(f"Font file does not exist: {args.font}")

    try:
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Install project requirements first."
        ) from error

    font = TTFont(args.font)
    if "glyf" not in font:
        raise SystemExit("This script only supports TrueType fonts with a glyf table.")

    glyf = font["glyf"]
    glyphs_to_process = selected_glyphs(font.getGlyphOrder(), args.glyphs)
    all_changes: list[Change] = []
    comparisons: list[GlyphComparison] = []
    removed_points = 0

    for glyph_name in font.getGlyphOrder():
        if glyph_name not in glyphs_to_process:
            continue
        glyph = glyf[glyph_name]
        if glyph.isComposite() or glyph.numberOfContours <= 0:
            continue

        coords = [tuple(point) for point in glyph.coordinates]
        flags = list(glyph.flags)
        end_points = list(glyph.endPtsOfContours)
        before_snapshot = make_snapshot(glyph_name, coords, flags, end_points)
        original_point_count = len(coords)
        glyph_changes: list[Change] = []

        if not args.no_remove_colinear:
            glyph_changes.extend(
                remove_colinear_points(
                    glyph_name,
                    coords,
                    flags,
                    end_points,
                    args.max_colinear_distance,
                    args.colinear_angle_tolerance,
                )
            )

        if not args.no_snap_semi:
            glyph_changes.extend(
                snap_semi_vertical_lines(
                    glyph_name,
                    coords,
                    flags,
                    end_points,
                    args.max_snap_units,
                    args.semi_angle_tolerance,
                )
            )

        if not args.no_remove_colinear:
            glyph_changes.extend(
                remove_colinear_points(
                    glyph_name,
                    coords,
                    flags,
                    end_points,
                    args.max_colinear_distance,
                    args.colinear_angle_tolerance,
                )
            )

        if not glyph_changes:
            continue

        all_changes.extend(glyph_changes)
        removed_points += original_point_count - len(coords)
        comparisons.append(
            GlyphComparison(
                glyph_name,
                before_snapshot,
                make_snapshot(glyph_name, coords, flags, end_points),
            )
        )

        if not args.dry_run:
            glyph.coordinates = GlyphCoordinates(coords)
            glyph.flags = bytearray(flags)
            glyph.endPtsOfContours = end_points
            glyph.numberOfContours = len(end_points)
            glyph.recalcBounds(glyf)

    for change in all_changes:
        print(f"{change.glyph}: {change.message}")

    print(
        f"Changed {len({change.glyph for change in all_changes})} glyph(s); "
        f"removed {removed_points} point(s)."
    )

    if args.comparison_image:
        write_comparison_image(comparisons, args.comparison_image)

    if args.dry_run:
        print("Dry run only; no font written.")
        return 0

    if removed_points and args.drop_hints:
        clear_hints(font)
        print("Dropped TrueType hints because --drop-hints was requested.")
    elif removed_points:
        print("WARNING: points were removed while keeping hints; validate carefully.")

    output_path = args.output or args.font
    font.recalcBBoxes = True
    font.save(output_path)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
