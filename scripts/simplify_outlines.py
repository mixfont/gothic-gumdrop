#!/usr/bin/env python3
"""Aggressively simplify TrueType outlines with geometric guardrails.

This is intentionally separate from the default build. It tries removing
simple-glyph points one at a time, compares the affected contour against the
original contour, and only keeps deletions that stay inside the configured
deviation limits.
"""

from __future__ import annotations

import argparse
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import repeat
from pathlib import Path
from typing import Sequence

from cleanup_outlines import (
    ON_CURVE,
    GlyphComparison,
    clear_hints,
    contour_ranges,
    delete_point,
    draw_snapshot,
    flatten_contour,
    make_snapshot,
    remove_colinear_points,
    snap_semi_vertical_lines,
    snapshot_bounds,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FONT = REPO_ROOT / "fonts/ttf/GothicGumdrop-Regular.ttf"
DEFAULT_COMPARISON_IMAGE = REPO_ROOT / "build/outline-simplification-preview.png"
DEFAULT_JOBS = min(max((os.cpu_count() or 2) - 1, 1), 8)


@dataclass(frozen=True)
class SimplificationSettings:
    max_deviation: float
    max_mean_deviation: float
    max_bounds_deviation: float
    max_area_change_ratio: float
    passes: int
    max_removals_per_glyph: int
    min_contour_points: int = 4
    flatten_steps: int = 12
    sample_spacing: float = 10.0
    min_samples: int = 32
    max_samples: int = 96
    local_reject_factor: float = 3.0
    cleanup_colinear_distance: float = 3.5
    cleanup_colinear_angle_tolerance: float = math.degrees(0.1)
    cleanup_snap_units: int = 3
    cleanup_semi_angle_tolerance: float = 0.5


AGGRESSIVENESS_PRESETS = {
    "conservative": SimplificationSettings(
        max_deviation=0.6,
        max_mean_deviation=0.10,
        max_bounds_deviation=0.6,
        max_area_change_ratio=0.005,
        passes=2,
        max_removals_per_glyph=24,
    ),
    "normal": SimplificationSettings(
        max_deviation=1.0,
        max_mean_deviation=0.18,
        max_bounds_deviation=1.0,
        max_area_change_ratio=0.01,
        passes=4,
        max_removals_per_glyph=48,
    ),
    "aggressive": SimplificationSettings(
        max_deviation=1.5,
        max_mean_deviation=0.28,
        max_bounds_deviation=1.5,
        max_area_change_ratio=0.02,
        passes=6,
        max_removals_per_glyph=80,
        cleanup_colinear_distance=4.5,
        cleanup_snap_units=4,
    ),
}


@dataclass(frozen=True)
class ContourReference:
    points: tuple[tuple[float, float], ...]
    flags: tuple[int, ...]
    flat: tuple[tuple[float, float], ...]
    area: float
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class Deviation:
    max_distance: float
    mean_distance: float
    bounds_delta: float
    area_delta_ratio: float


@dataclass(frozen=True)
class Removal:
    glyph: str
    contour: int
    contour_point: int
    absolute_point: int
    point_type: str
    x: float
    y: float
    deviation: Deviation


@dataclass(frozen=True)
class GlyphResult:
    name: str
    removed: int
    point_count_before: int
    point_count_after: int
    max_distance: float
    mean_distance: float
    bounds_delta: float
    area_delta_ratio: float


@dataclass(frozen=True)
class GlyphTask:
    name: str
    coords: tuple[tuple[int, int], ...]
    flags: tuple[int, ...]
    end_points: tuple[int, ...]


@dataclass(frozen=True)
class ProcessedGlyph:
    name: str
    coords: tuple[tuple[int, int], ...]
    flags: tuple[int, ...]
    end_points: tuple[int, ...]
    result: GlyphResult
    comparison: GlyphComparison
    removed_points: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Simplify fonts/ttf/GothicGumdrop-Regular.ttf by deleting "
            "outline points that do not materially change the design."
        )
    )
    parser.add_argument(
        "--aggressiveness",
        choices=tuple(AGGRESSIVENESS_PRESETS),
        default="normal",
        help=(
            "Node-removal strength. Conservative removes fewer points; "
            "aggressive allows more outline drift. Defaults to normal."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview changes without updating the font. This writes a "
            "before/after comparison image."
        ),
    )
    parser.add_argument(
        "--comparison-image",
        type=Path,
        default=DEFAULT_COMPARISON_IMAGE,
        help=(
            "Dry-run preview image path. Defaults to "
            f"{DEFAULT_COMPARISON_IMAGE.relative_to(REPO_ROOT)}."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"Parallel worker processes. Defaults to {DEFAULT_JOBS}.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def contour_start(end_points: Sequence[int], contour_index: int) -> int:
    if contour_index == 0:
        return 0
    return end_points[contour_index - 1] + 1


def contour_points(
    coords: Sequence[tuple[float, float]],
    flags: Sequence[int],
    start: int,
    end: int,
) -> tuple[tuple[tuple[float, float], ...], tuple[int, ...]]:
    return tuple(coords[start : end + 1]), tuple(flags[start : end + 1])


def bounds(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    if not points:
        return 0.0, 0.0, 0.0, 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def signed_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for first, second in zip(points, points[1:]):
        area += first[0] * second[1] - second[0] * first[1]
    return area / 2.0


def polyline_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in zip(points, points[1:])
    )


def sample_count_for(
    points: Sequence[tuple[float, float]],
    spacing: float,
    min_samples: int,
    max_samples: int,
) -> int:
    if not points:
        return 0
    if spacing <= 0:
        return max_samples
    count = int(math.ceil(polyline_length(points) / spacing))
    return max(min_samples, min(max_samples, count))


def resample_polyline(
    points: Sequence[tuple[float, float]],
    sample_count: int,
) -> list[tuple[float, float]]:
    if not points or sample_count <= 0:
        return []
    if len(points) == 1 or sample_count == 1:
        return [points[0]]

    segment_lengths = [
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in zip(points, points[1:])
    ]
    total = sum(segment_lengths)
    if total == 0:
        return [points[0]] * sample_count

    samples = []
    segment_index = 0
    distance_before_segment = 0.0

    for sample_index in range(sample_count):
        target = total * sample_index / (sample_count - 1)
        while (
            segment_index < len(segment_lengths) - 1
            and distance_before_segment + segment_lengths[segment_index] < target
        ):
            distance_before_segment += segment_lengths[segment_index]
            segment_index += 1

        first = points[segment_index]
        second = points[segment_index + 1]
        segment_length = segment_lengths[segment_index]
        if segment_length == 0:
            samples.append(first)
            continue

        t = (target - distance_before_segment) / segment_length
        samples.append(
            (
                first[0] + (second[0] - first[0]) * t,
                first[1] + (second[1] - first[1]) * t,
            )
        )

    return samples


def point_to_segment_distance_squared(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    if dx == 0 and dy == 0:
        point_dx = point[0] - first[0]
        point_dy = point[1] - first[1]
        return point_dx * point_dx + point_dy * point_dy

    t = ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / (
        dx * dx + dy * dy
    )
    t = max(0.0, min(1.0, t))
    projection = (first[0] + t * dx, first[1] + t * dy)
    point_dx = point[0] - projection[0]
    point_dy = point[1] - projection[1]
    return point_dx * point_dx + point_dy * point_dy


def point_to_segment_distance(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.sqrt(point_to_segment_distance_squared(point, first, second))


def point_to_polyline_distance(
    point: tuple[float, float],
    polyline: Sequence[tuple[float, float]],
) -> float:
    if not polyline:
        return math.inf
    if len(polyline) == 1:
        return math.hypot(point[0] - polyline[0][0], point[1] - polyline[0][1])
    best_squared = math.inf
    for first, second in zip(polyline, polyline[1:]):
        distance_squared = point_to_segment_distance_squared(point, first, second)
        if distance_squared < best_squared:
            best_squared = distance_squared
    return math.sqrt(best_squared)


def directed_distances(
    samples: Sequence[tuple[float, float]],
    polyline: Sequence[tuple[float, float]],
) -> list[float]:
    return [point_to_polyline_distance(point, polyline) for point in samples]


def make_contour_reference(
    points: Sequence[tuple[float, float]],
    flags: Sequence[int],
    flatten_steps: int,
) -> ContourReference:
    flat = tuple(flatten_contour(points, flags, steps=flatten_steps))
    return ContourReference(
        points=tuple(points),
        flags=tuple(flags),
        flat=flat,
        area=signed_area(flat),
        bounds=bounds(flat),
    )


def compare_contour(
    reference: ContourReference,
    points: Sequence[tuple[float, float]],
    flags: Sequence[int],
    flatten_steps: int,
    sample_spacing: float,
    min_samples: int,
    max_samples: int,
) -> Deviation:
    candidate_flat = tuple(flatten_contour(points, flags, steps=flatten_steps))
    if not reference.flat or not candidate_flat:
        return Deviation(math.inf, math.inf, math.inf, math.inf)

    sample_count = max(
        sample_count_for(reference.flat, sample_spacing, min_samples, max_samples),
        sample_count_for(candidate_flat, sample_spacing, min_samples, max_samples),
    )
    reference_samples = resample_polyline(reference.flat, sample_count)
    candidate_samples = resample_polyline(candidate_flat, sample_count)

    distances = directed_distances(reference_samples, candidate_samples)
    distances.extend(directed_distances(candidate_samples, reference_samples))

    candidate_bounds = bounds(candidate_flat)
    bounds_delta = max(
        abs(reference_value - candidate_value)
        for reference_value, candidate_value in zip(reference.bounds, candidate_bounds)
    )

    candidate_area = signed_area(candidate_flat)
    if reference.area and candidate_area and reference.area * candidate_area < 0:
        area_delta_ratio = math.inf
    else:
        area_delta_ratio = abs(abs(reference.area) - abs(candidate_area)) / max(
            abs(reference.area), 1.0
        )

    return Deviation(
        max_distance=max(distances) if distances else math.inf,
        mean_distance=sum(distances) / len(distances) if distances else math.inf,
        bounds_delta=bounds_delta,
        area_delta_ratio=area_delta_ratio,
    )


def delete_point_copy(
    coords: Sequence[tuple[int, int]],
    flags: Sequence[int],
    end_points: Sequence[int],
    index: int,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    next_coords = list(coords)
    next_flags = list(flags)
    next_end_points = list(end_points)
    delete_point(next_coords, next_flags, next_end_points, index)
    return next_coords, next_flags, next_end_points


def can_delete_point(
    flags: Sequence[int],
    end_points: Sequence[int],
    contour_index: int,
    index: int,
    min_contour_points: int,
) -> bool:
    start = contour_start(end_points, contour_index)
    end = end_points[contour_index]
    if end - start + 1 <= min_contour_points:
        return False

    on_curve_count = sum(
        1 for point_index in range(start, end + 1) if flags[point_index] & ON_CURVE
    )
    return not (flags[index] & ON_CURVE and on_curve_count <= 1)


def previous_point_index(start: int, end: int, index: int) -> int:
    return end if index == start else index - 1


def next_point_index(start: int, end: int, index: int) -> int:
    return start if index == end else index + 1


def local_rejects_candidate(
    coords: Sequence[tuple[int, int]],
    end_points: Sequence[int],
    contour_index: int,
    index: int,
    max_distance: float,
) -> bool:
    if max_distance <= 0:
        return False

    start = contour_start(end_points, contour_index)
    end = end_points[contour_index]
    previous_index = previous_point_index(start, end, index)
    next_index = next_point_index(start, end, index)
    distance = point_to_segment_distance(
        coords[index],
        coords[previous_index],
        coords[next_index],
    )
    return distance > max_distance


def deviation_is_allowed(
    settings: SimplificationSettings, deviation: Deviation
) -> bool:
    return (
        deviation.max_distance <= settings.max_deviation
        and deviation.mean_distance <= settings.max_mean_deviation
        and deviation.bounds_delta <= settings.max_bounds_deviation
        and deviation.area_delta_ratio <= settings.max_area_change_ratio
    )


def simplify_glyph(
    glyph_name: str,
    coords: list[tuple[int, int]],
    flags: list[int],
    end_points: list[int],
    settings: SimplificationSettings,
) -> tuple[list[tuple[int, int]], list[int], list[int], list[Removal]]:
    references: list[ContourReference] = []
    for start, end in contour_ranges(end_points):
        points, point_flags = contour_points(coords, flags, start, end)
        references.append(
            make_contour_reference(points, point_flags, settings.flatten_steps)
        )

    removals: list[Removal] = []

    for _pass_index in range(max(settings.passes, 0)):
        changed_in_pass = False
        contour_index = 0

        while contour_index < len(end_points):
            point_index = contour_start(end_points, contour_index)

            while point_index <= end_points[contour_index]:
                if (
                    settings.max_removals_per_glyph
                    and len(removals) >= settings.max_removals_per_glyph
                ):
                    return coords, flags, end_points, removals

                if not can_delete_point(
                    flags,
                    end_points,
                    contour_index,
                    point_index,
                    settings.min_contour_points,
                ):
                    point_index += 1
                    continue

                local_reject_distance = (
                    settings.max_deviation * settings.local_reject_factor
                )
                if local_rejects_candidate(
                    coords,
                    end_points,
                    contour_index,
                    point_index,
                    local_reject_distance,
                ):
                    point_index += 1
                    continue

                candidate_coords, candidate_flags, candidate_end_points = (
                    delete_point_copy(coords, flags, end_points, point_index)
                )
                candidate_start = contour_start(candidate_end_points, contour_index)
                candidate_end = candidate_end_points[contour_index]
                candidate_points, candidate_point_flags = contour_points(
                    candidate_coords,
                    candidate_flags,
                    candidate_start,
                    candidate_end,
                )
                deviation = compare_contour(
                    references[contour_index],
                    candidate_points,
                    candidate_point_flags,
                    settings.flatten_steps,
                    settings.sample_spacing,
                    settings.min_samples,
                    settings.max_samples,
                )

                if not deviation_is_allowed(settings, deviation):
                    point_index += 1
                    continue

                point = coords[point_index]
                point_type = "on" if flags[point_index] & ON_CURVE else "off"
                removals.append(
                    Removal(
                        glyph=glyph_name,
                        contour=contour_index,
                        contour_point=point_index
                        - contour_start(end_points, contour_index),
                        absolute_point=point_index,
                        point_type=point_type,
                        x=float(point[0]),
                        y=float(point[1]),
                        deviation=deviation,
                    )
                )

                coords, flags, end_points = (
                    candidate_coords,
                    candidate_flags,
                    candidate_end_points,
                )
                changed_in_pass = True
                point_index = max(
                    contour_start(end_points, contour_index),
                    point_index - 1,
                )

            contour_index += 1

        if not changed_in_pass:
            break

    return coords, flags, end_points, removals


def run_outline_cleanup(
    glyph_name: str,
    coords: list[tuple[int, int]],
    flags: list[int],
    end_points: list[int],
    settings: SimplificationSettings,
) -> int:
    point_count_before = len(coords)
    remove_colinear_points(
        glyph_name,
        coords,
        flags,
        end_points,
        settings.cleanup_colinear_distance,
        settings.cleanup_colinear_angle_tolerance,
    )
    snap_semi_vertical_lines(
        glyph_name,
        coords,
        flags,
        end_points,
        settings.cleanup_snap_units,
        settings.cleanup_semi_angle_tolerance,
    )
    remove_colinear_points(
        glyph_name,
        coords,
        flags,
        end_points,
        settings.cleanup_colinear_distance,
        settings.cleanup_colinear_angle_tolerance,
    )
    return point_count_before - len(coords)


def result_from_removals(
    glyph_name: str,
    point_count_before: int,
    point_count_after: int,
    removals: Sequence[Removal],
) -> GlyphResult:
    max_distance = max(
        (removal.deviation.max_distance for removal in removals),
        default=0.0,
    )
    mean_distance = max(
        (removal.deviation.mean_distance for removal in removals),
        default=0.0,
    )
    bounds_delta = max(
        (removal.deviation.bounds_delta for removal in removals),
        default=0.0,
    )
    area_delta_ratio = max(
        (removal.deviation.area_delta_ratio for removal in removals),
        default=0.0,
    )
    return GlyphResult(
        name=glyph_name,
        removed=point_count_before - point_count_after,
        point_count_before=point_count_before,
        point_count_after=point_count_after,
        max_distance=max_distance,
        mean_distance=mean_distance,
        bounds_delta=bounds_delta,
        area_delta_ratio=area_delta_ratio,
    )


def process_glyph_task(
    task: GlyphTask,
    settings: SimplificationSettings,
) -> ProcessedGlyph | None:
    coords = list(task.coords)
    flags = list(task.flags)
    end_points = list(task.end_points)
    before_snapshot = make_snapshot(task.name, coords, flags, end_points)
    point_count_before = len(coords)

    next_coords, next_flags, next_end_points, removals = simplify_glyph(
        task.name,
        coords,
        flags,
        end_points,
        settings,
    )
    cleanup_removed = run_outline_cleanup(
        task.name,
        next_coords,
        next_flags,
        next_end_points,
        settings,
    )

    if not removals and not cleanup_removed:
        return None

    return ProcessedGlyph(
        name=task.name,
        coords=tuple(next_coords),
        flags=tuple(next_flags),
        end_points=tuple(next_end_points),
        result=result_from_removals(
            task.name,
            point_count_before,
            len(next_coords),
            removals,
        ),
        comparison=GlyphComparison(
            task.name,
            before_snapshot,
            make_snapshot(task.name, next_coords, next_flags, next_end_points),
        ),
        removed_points=point_count_before - len(next_coords),
    )


def process_glyphs(
    tasks: Sequence[GlyphTask],
    settings: SimplificationSettings,
    jobs: int,
) -> list[ProcessedGlyph]:
    jobs = max(jobs, 1)
    if jobs == 1:
        return [
            result
            for result in (process_glyph_task(task, settings) for task in tasks)
            if result is not None
        ]

    chunksize = max(1, len(tasks) // (jobs * 4))
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        results = executor.map(
            process_glyph_task,
            tasks,
            repeat(settings),
            chunksize=chunksize,
        )
        return [result for result in results if result is not None]


def write_black_comparison_image(
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
    draw.text((margin, 16), headings[0], fill=(0, 0, 0), font=font)
    x = margin + label_width
    for heading in headings[1:]:
        draw.text((x + 8, 16), heading, fill=(0, 0, 0), font=font)
        x += panel_width + gap

    for row, comparison in enumerate(comparisons):
        y = header_height + row * row_height
        row_bottom = y + row_height - 10
        draw.rectangle(
            (0, y, image_width, row_bottom),
            fill="white",
        )
        draw.line((margin, y, image_width - margin, y), fill=(220, 220, 220))
        draw.text((margin, y + 16), comparison.name, fill=(0, 0, 0), font=font)

        bounds = snapshot_bounds([comparison.before, comparison.after])
        x = margin + label_width
        for snapshot in (comparison.before, comparison.after):
            box = (x, y + 18, x + panel_width, row_bottom)
            draw.rectangle(box, fill="white", outline=(210, 210, 210))
            draw_snapshot(draw, snapshot, bounds, box, (0, 0, 0), width=4)
            x += panel_width + gap

        overlay_box = (x, y + 18, x + panel_width, row_bottom)
        draw.rectangle(overlay_box, fill="white", outline=(210, 210, 210))
        draw_snapshot(
            draw,
            comparison.before,
            bounds,
            overlay_box,
            (175, 175, 175),
            width=4,
        )
        draw_snapshot(
            draw,
            comparison.after,
            bounds,
            overlay_box,
            (0, 0, 0),
            width=4,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"Wrote comparison image: {path}")


def set_smart_dropout_prep(font) -> None:
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables.ttProgram import Program

    program = Program()
    program.fromAssembly(
        [
            "PUSHW[]",
            "511",
            "SCANCTRL[]",
            "PUSHB[]",
            "4",
            "SCANTYPE[]",
        ]
    )

    prep = newTable("prep")
    prep.program = program
    font["prep"] = prep


def main() -> int:
    args = parse_args()
    settings = AGGRESSIVENESS_PRESETS[args.aggressiveness]
    font_path = DEFAULT_FONT

    if not font_path.exists():
        raise SystemExit(f"Font file does not exist: {font_path}")

    try:
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Missing dependency: fontTools. Install project requirements first."
        ) from error

    font = TTFont(font_path)
    if "glyf" not in font:
        raise SystemExit("This script only supports TrueType fonts with a glyf table.")

    glyf = font["glyf"]
    tasks: list[GlyphTask] = []

    print(
        f"Simplifying {font_path.relative_to(REPO_ROOT)} "
        f"with {args.aggressiveness} aggressiveness using "
        f"{max(args.jobs, 1)} job(s)..."
    )

    for glyph_name in font.getGlyphOrder():
        glyph = glyf[glyph_name]
        if glyph.isComposite() or glyph.numberOfContours <= 0:
            continue

        tasks.append(
            GlyphTask(
                name=glyph_name,
                coords=tuple(tuple(point) for point in glyph.coordinates),
                flags=tuple(glyph.flags),
                end_points=tuple(glyph.endPtsOfContours),
            )
        )

    processed_glyphs = process_glyphs(tasks, settings, args.jobs)
    glyph_results = [processed.result for processed in processed_glyphs]
    comparisons = [processed.comparison for processed in processed_glyphs]
    total_removed_points = sum(
        processed.removed_points for processed in processed_glyphs
    )

    for processed in processed_glyphs:
        if not args.dry_run:
            glyph = glyf[processed.name]
            glyph.coordinates = GlyphCoordinates(processed.coords)
            glyph.flags = bytearray(processed.flags)
            glyph.endPtsOfContours = list(processed.end_points)
            glyph.numberOfContours = len(processed.end_points)
            glyph.recalcBounds(glyf)

    print(
        f"Changed {len(glyph_results)} glyph(s); "
        f"removed {total_removed_points} point(s)."
    )

    if args.dry_run:
        comparison_path = resolve_path(args.comparison_image)
        write_black_comparison_image(comparisons, comparison_path)
        print("Dry run only; no font written.")
        return 0

    if glyph_results:
        clear_hints(font)
        set_smart_dropout_prep(font)
        print("Dropped stale hints and added minimal smart-dropout prep.")

    font.recalcBBoxes = True
    font.save(font_path)
    print(f"Wrote {font_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
