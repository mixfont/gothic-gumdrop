#!/usr/bin/env python3
"""Measure likely stem inconsistencies and draw a comparison PNG.

This is a heuristic QA helper, not a substitute for type-design review. It
samples filled outline spans through each glyph and compares the dominant
vertical and horizontal stroke thickness against the median for its group.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FONT = REPO_ROOT / "fonts/ttf/GothicGumdrop-Regular.ttf"
DEFAULT_IMAGE = REPO_ROOT / "build/stem-comparison.png"
DEFAULT_REPORT = REPO_ROOT / "build/stem-analysis.txt"

SCAN_FRACTIONS = (0.16, 0.22, 0.30, 0.38, 0.46, 0.54, 0.62, 0.70, 0.78, 0.84)
GROUPS = (
    ("Uppercase", tuple(range(0x41, 0x5B))),
    ("Lowercase", tuple(range(0x61, 0x7B))),
    ("Digits", tuple(range(0x30, 0x3A))),
)


Point = tuple[float, float]
Contour = list[Point]


@dataclass(frozen=True)
class GlyphMeasurement:
    group: str
    codepoint: int
    glyph_name: str
    char: str
    bounds: tuple[float, float, float, float]
    vertical_stem: float | None
    horizontal_stem: float | None
    vertical_samples: int
    horizontal_samples: int
    vertical_range: tuple[float, float] | None
    horizontal_range: tuple[float, float] | None


@dataclass(frozen=True)
class GroupSummary:
    name: str
    measurements: tuple[GlyphMeasurement, ...]
    vertical_median: float | None
    horizontal_median: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure sampled stem widths in the built TTF and create a visual "
            "comparison image plus a text report."
        )
    )
    parser.add_argument(
        "font",
        nargs="?",
        type=Path,
        default=DEFAULT_FONT,
        help=f"Font to analyze. Defaults to {DEFAULT_FONT.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "-o",
        "--output-image",
        type=Path,
        default=DEFAULT_IMAGE,
        help=f"PNG comparison image. Defaults to {DEFAULT_IMAGE.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Text report. Defaults to {DEFAULT_REPORT.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "--threshold-ratio",
        type=float,
        default=0.18,
        help="Relative deviation from group median to flag. Defaults to 0.18.",
    )
    parser.add_argument(
        "--threshold-units",
        type=float,
        default=18.0,
        help="Minimum absolute deviation in font units to flag. Defaults to 18.",
    )
    parser.add_argument(
        "--flatten-steps",
        type=int,
        default=24,
        help="Bezier flattening steps per curve segment. Defaults to 24.",
    )
    parser.add_argument(
        "--include-horizontal",
        action="store_true",
        help=(
            "Also flag sampled horizontal spans. This is noisier on diagonal "
            "and bowl-heavy glyphs, so vertical stems are the default."
        ),
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def quadratic_point(start: Point, control: Point, end: Point, t: float) -> Point:
    mt = 1 - t
    return (
        mt * mt * start[0] + 2 * mt * t * control[0] + t * t * end[0],
        mt * mt * start[1] + 2 * mt * t * control[1] + t * t * end[1],
    )


def cubic_point(start: Point, first: Point, second: Point, end: Point, t: float) -> Point:
    mt = 1 - t
    return (
        mt**3 * start[0]
        + 3 * mt * mt * t * first[0]
        + 3 * mt * t * t * second[0]
        + t**3 * end[0],
        mt**3 * start[1]
        + 3 * mt * mt * t * first[1]
        + 3 * mt * t * t * second[1]
        + t**3 * end[1],
    )


def flatten_glyph(font: TTFont, glyph_name: str, steps: int) -> list[Contour]:
    glyph_set = font.getGlyphSet()
    recording = RecordingPen()
    glyph_set[glyph_name].draw(recording)

    contours: list[Contour] = []
    points: Contour = []
    current: Point | None = None
    start: Point | None = None

    def close_contour() -> None:
        nonlocal points, current, start
        if points:
            if points[0] != points[-1]:
                points.append(points[0])
            contours.append(points)
        points = []
        current = None
        start = None

    for operation, args in recording.value:
        if operation == "moveTo":
            if points:
                close_contour()
            current = args[0]
            start = current
            points = [current]
        elif operation == "lineTo":
            current = args[0]
            points.append(current)
        elif operation == "qCurveTo":
            if current is None:
                continue
            qpoints = list(args)
            if qpoints and qpoints[-1] is None:
                if start is None:
                    continue
                qpoints = qpoints[:-1] + [start]
            if not qpoints:
                continue

            controls = qpoints[:-1]
            final = qpoints[-1]
            segment_start = current
            for index, control in enumerate(controls):
                if index < len(controls) - 1:
                    end = (
                        (control[0] + controls[index + 1][0]) / 2,
                        (control[1] + controls[index + 1][1]) / 2,
                    )
                else:
                    end = final
                for step in range(1, steps + 1):
                    points.append(quadratic_point(segment_start, control, end, step / steps))
                segment_start = end
            current = final
        elif operation == "curveTo":
            if current is None:
                continue
            first, second, end = args
            for step in range(1, steps + 1):
                points.append(cubic_point(current, first, second, end, step / steps))
            current = end
        elif operation in {"closePath", "endPath"}:
            close_contour()

    if points:
        close_contour()

    return contours


def contour_bounds(contours: Sequence[Contour]) -> tuple[float, float, float, float] | None:
    points = [point for contour in contours for point in contour]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def intervals_at_y(contours: Sequence[Contour], y: float) -> list[tuple[float, float]]:
    intersections: list[float] = []
    for contour in contours:
        for first, second in zip(contour, contour[1:]):
            x1, y1 = first
            x2, y2 = second
            if y1 == y2:
                continue
            if min(y1, y2) <= y < max(y1, y2):
                t = (y - y1) / (y2 - y1)
                intersections.append(x1 + t * (x2 - x1))
    intersections.sort()
    return [
        (intersections[index], intersections[index + 1])
        for index in range(0, len(intersections) - 1, 2)
        if intersections[index + 1] > intersections[index]
    ]


def intervals_at_x(contours: Sequence[Contour], x: float) -> list[tuple[float, float]]:
    intersections: list[float] = []
    for contour in contours:
        for first, second in zip(contour, contour[1:]):
            x1, y1 = first
            x2, y2 = second
            if x1 == x2:
                continue
            if min(x1, x2) <= x < max(x1, x2):
                t = (x - x1) / (x2 - x1)
                intersections.append(y1 + t * (y2 - y1))
    intersections.sort()
    return [
        (intersections[index], intersections[index + 1])
        for index in range(0, len(intersections) - 1, 2)
        if intersections[index + 1] > intersections[index]
    ]


def accepted_span(span: float, glyph_dimension: float) -> bool:
    min_span = max(10.0, glyph_dimension * 0.025)
    if glyph_dimension < 260:
        max_span = min(240.0, glyph_dimension * 1.05)
    else:
        max_span = min(240.0, glyph_dimension * 0.55)
    return min_span <= span <= max_span


def dominant_span(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    return median(values)


def measure_glyph(
    font: TTFont,
    group_name: str,
    codepoint: int,
    glyph_name: str,
    steps: int,
) -> GlyphMeasurement | None:
    contours = flatten_glyph(font, glyph_name, steps)
    bounds = contour_bounds(contours)
    if bounds is None:
        return None

    x_min, y_min, x_max, y_max = bounds
    width = x_max - x_min
    height = y_max - y_min
    if width <= 0 or height <= 0:
        return None

    vertical_spans: list[float] = []
    horizontal_spans: list[float] = []

    for fraction in SCAN_FRACTIONS:
        y = y_min + height * fraction
        for start, end in intervals_at_y(contours, y):
            span = end - start
            if accepted_span(span, width):
                vertical_spans.append(span)

    for fraction in SCAN_FRACTIONS:
        x = x_min + width * fraction
        for start, end in intervals_at_x(contours, x):
            span = end - start
            if accepted_span(span, height):
                horizontal_spans.append(span)

    vertical_range = (min(vertical_spans), max(vertical_spans)) if vertical_spans else None
    horizontal_range = (min(horizontal_spans), max(horizontal_spans)) if horizontal_spans else None
    return GlyphMeasurement(
        group=group_name,
        codepoint=codepoint,
        glyph_name=glyph_name,
        char=chr(codepoint),
        bounds=bounds,
        vertical_stem=dominant_span(vertical_spans),
        horizontal_stem=dominant_span(horizontal_spans),
        vertical_samples=len(vertical_spans),
        horizontal_samples=len(horizontal_spans),
        vertical_range=vertical_range,
        horizontal_range=horizontal_range,
    )


def analyze_font(font_path: Path, steps: int) -> tuple[GroupSummary, ...]:
    font = TTFont(str(font_path))
    cmap = font.getBestCmap()
    summaries: list[GroupSummary] = []

    for group_name, codepoints in GROUPS:
        measurements: list[GlyphMeasurement] = []
        for codepoint in codepoints:
            glyph_name = cmap.get(codepoint)
            if glyph_name is None:
                continue
            measurement = measure_glyph(font, group_name, codepoint, glyph_name, steps)
            if measurement is not None:
                measurements.append(measurement)

        vertical_values = [m.vertical_stem for m in measurements if m.vertical_stem is not None]
        horizontal_values = [
            m.horizontal_stem for m in measurements if m.horizontal_stem is not None
        ]
        summaries.append(
            GroupSummary(
                name=group_name,
                measurements=tuple(measurements),
                vertical_median=median(vertical_values) if vertical_values else None,
                horizontal_median=median(horizontal_values) if horizontal_values else None,
            )
        )

    return tuple(summaries)


def deviation(
    value: float | None,
    reference: float | None,
    threshold_units: float,
    threshold_ratio: float,
) -> float | None:
    if value is None or reference is None:
        return None
    delta = value - reference
    threshold = max(threshold_units, reference * threshold_ratio)
    if abs(delta) < threshold:
        return None
    return delta


def outlier_lines(
    summaries: Sequence[GroupSummary],
    threshold_units: float,
    threshold_ratio: float,
    include_horizontal: bool = False,
) -> list[str]:
    lines: list[str] = []
    for summary in summaries:
        for measurement in summary.measurements:
            vertical_delta = deviation(
                measurement.vertical_stem,
                summary.vertical_median,
                threshold_units,
                threshold_ratio,
            )
            horizontal_delta = (
                deviation(
                    measurement.horizontal_stem,
                    summary.horizontal_median,
                    threshold_units,
                    threshold_ratio,
                )
                if include_horizontal
                else None
            )
            if vertical_delta is None and horizontal_delta is None:
                continue

            parts = []
            if vertical_delta is not None and measurement.vertical_stem is not None:
                parts.append(
                    f"vertical {measurement.vertical_stem:.1f} ({vertical_delta:+.1f})"
                )
            if horizontal_delta is not None and measurement.horizontal_stem is not None:
                parts.append(
                    f"horizontal {measurement.horizontal_stem:.1f} ({horizontal_delta:+.1f})"
                )
            lines.append(
                f"{summary.name} {measurement.char} ({measurement.glyph_name}): "
                + ", ".join(parts)
            )
    return lines


def write_report(
    report_path: Path,
    font_path: Path,
    summaries: Sequence[GroupSummary],
    threshold_units: float,
    threshold_ratio: float,
    include_horizontal: bool,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Stem analysis for {font_path}",
        "",
        "Method: sampled filled outline spans across each glyph. Values are font units.",
        "Diagonal and bowl-heavy glyphs can be false positives; use this as a review queue.",
        "",
    ]

    for summary in summaries:
        lines.append(
            f"{summary.name}: vertical median "
            f"{format_value(summary.vertical_median)}, horizontal median "
            f"{format_value(summary.horizontal_median)}"
        )
        missing_vertical = [
            m.char for m in summary.measurements if m.vertical_stem is None
        ]
        missing_horizontal = [
            m.char for m in summary.measurements if m.horizontal_stem is None
        ]
        if missing_vertical:
            lines.append(f"  Too few vertical samples: {' '.join(missing_vertical)}")
        if missing_horizontal:
            lines.append(f"  Too few horizontal samples: {' '.join(missing_horizontal)}")
        lines.append("")

    lines.append("Largest vertical-stem deviations:")
    for summary in summaries:
        values = [
            measurement
            for measurement in summary.measurements
            if measurement.vertical_stem is not None and summary.vertical_median is not None
        ]
        values.sort(
            key=lambda measurement: abs(
                (measurement.vertical_stem or 0) - (summary.vertical_median or 0)
            ),
            reverse=True,
        )
        rendered = []
        for measurement in values[:8]:
            delta = (measurement.vertical_stem or 0) - (summary.vertical_median or 0)
            rendered.append(f"{measurement.char} {measurement.vertical_stem:.1f} ({delta:+.1f})")
        lines.append(f"  {summary.name}: {', '.join(rendered)}")
    lines.append("")

    label = "Possible vertical stem inconsistencies"
    if include_horizontal:
        label += " and horizontal span inconsistencies"
    lines.append(f"{label}:")
    possible = outlier_lines(
        summaries,
        threshold_units,
        threshold_ratio,
        include_horizontal=include_horizontal,
    )
    if possible:
        lines.extend(f"  {line}" for line in possible)
    else:
        lines.append("  None at the configured threshold.")

    if not include_horizontal:
        lines.extend(
            [
                "",
                "Horizontal span values are shown in the PNG but are not flagged by default.",
                "Use --include-horizontal for a broader, noisier review queue.",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_value(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def load_text_font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def flag_color(delta: float | None) -> tuple[int, int, int]:
    if delta is None:
        return (122, 134, 148)
    if delta > 0:
        return (177, 68, 45)
    return (45, 97, 177)


def draw_text(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] = (29, 36, 45),
) -> None:
    draw.text(position, text, font=font, fill=fill)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def draw_metric_bar(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    label: str,
    value: float | None,
    reference: float | None,
    max_value: float,
    label_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    threshold_units: float,
    threshold_ratio: float,
    highlight: bool,
) -> None:
    draw_text(draw, (left, top), label, small_font, (60, 69, 80))
    bar_left = left + 20
    bar_width = 70
    bar_top = top + 4
    bar_height = 7
    draw.rectangle(
        (bar_left, bar_top, bar_left + bar_width, bar_top + bar_height),
        fill=(225, 229, 235),
    )

    if reference is not None:
        marker_x = bar_left + int(bar_width * min(reference / max_value, 1.0))
        draw.line((marker_x, bar_top - 2, marker_x, bar_top + bar_height + 2), fill=(44, 52, 62))

    if value is None:
        draw_text(draw, (bar_left + bar_width + 5, top - 2), "n/a", small_font, (100, 111, 124))
        return

    delta = (
        deviation(value, reference, threshold_units, threshold_ratio)
        if highlight
        else None
    )
    actual_width = int(bar_width * min(value / max_value, 1.0))
    draw.rectangle(
        (bar_left, bar_top, bar_left + actual_width, bar_top + bar_height),
        fill=flag_color(delta),
    )
    value_text = f"{value:.0f}"
    draw_text(draw, (bar_left + bar_width + 5, top - 2), value_text, small_font, flag_color(delta))


def draw_tile(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    tile_width: int,
    tile_height: int,
    measurement: GlyphMeasurement,
    summary: GroupSummary,
    glyph_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    threshold_units: float,
    threshold_ratio: float,
    include_horizontal: bool,
) -> None:
    vertical_delta = deviation(
        measurement.vertical_stem,
        summary.vertical_median,
        threshold_units,
        threshold_ratio,
    )
    horizontal_delta = (
        deviation(
            measurement.horizontal_stem,
            summary.horizontal_median,
            threshold_units,
            threshold_ratio,
        )
        if include_horizontal
        else None
    )
    border = (205, 211, 218)
    if vertical_delta is not None or horizontal_delta is not None:
        border = flag_color(vertical_delta if vertical_delta is not None else horizontal_delta)

    draw.rectangle((x, y, x + tile_width, y + tile_height), fill=(255, 255, 255), outline=border, width=2)

    glyph_bbox = draw.textbbox((0, 0), measurement.char, font=glyph_font)
    glyph_width = glyph_bbox[2] - glyph_bbox[0]
    glyph_height = glyph_bbox[3] - glyph_bbox[1]
    glyph_x = x + (tile_width - glyph_width) // 2 - glyph_bbox[0]
    glyph_y = y + 10 + (80 - glyph_height) // 2 - glyph_bbox[1]
    draw.text((glyph_x, glyph_y), measurement.char, font=glyph_font, fill=(30, 34, 40))

    name = f"{measurement.char} {measurement.glyph_name.replace('uni00', 'u+')}"
    name_x = x + max(6, (tile_width - text_width(draw, name, label_font)) // 2)
    draw_text(draw, (name_x, y + 92), name, label_font, (38, 45, 55))

    max_vertical = max(
        1.0,
        summary.vertical_median or 1.0,
        *(m.vertical_stem or 0 for m in summary.measurements),
    ) * 1.15
    max_horizontal = max(
        1.0,
        summary.horizontal_median or 1.0,
        *(m.horizontal_stem or 0 for m in summary.measurements),
    ) * 1.15

    draw_metric_bar(
        draw,
        x + 10,
        y + 120,
        "V",
        measurement.vertical_stem,
        summary.vertical_median,
        max_vertical,
        label_font,
        small_font,
        threshold_units,
        threshold_ratio,
        True,
    )
    draw_metric_bar(
        draw,
        x + 10,
        y + 143,
        "H",
        measurement.horizontal_stem,
        summary.horizontal_median,
        max_horizontal,
        label_font,
        small_font,
        threshold_units,
        threshold_ratio,
        include_horizontal,
    )


def write_image(
    image_path: Path,
    font_path: Path,
    summaries: Sequence[GroupSummary],
    threshold_units: float,
    threshold_ratio: float,
    include_horizontal: bool,
) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)

    columns = 10
    tile_width = 132
    tile_height = 176
    gap = 12
    margin = 36
    section_header = 58
    title_height = 98

    section_heights = []
    for summary in summaries:
        rows = math.ceil(len(summary.measurements) / columns)
        section_heights.append(section_header + rows * (tile_height + gap) + 22)
    width = margin * 2 + columns * tile_width + (columns - 1) * gap
    height = title_height + sum(section_heights) + margin

    image = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(image)
    title_font = load_text_font(30)
    section_font = load_text_font(22)
    label_font = load_text_font(12)
    small_font = load_text_font(11)
    glyph_font = ImageFont.truetype(str(font_path), 96)

    draw_text(draw, (margin, 28), "Gothic Gumdrop Stem Comparison", title_font, (24, 30, 38))
    subtitle = "V = flagged vertical stem width, H = unflagged sampled horizontal span. Marker shows group median."
    if include_horizontal:
        subtitle = "V and H are both flagged against their group medians. Marker shows group median."
    draw_text(draw, (margin, 64), subtitle, label_font, (78, 89, 104))

    y = title_height
    for summary in summaries:
        median_line = (
            f"{summary.name}    V median {format_value(summary.vertical_median)}    "
            f"H median {format_value(summary.horizontal_median)}"
        )
        draw_text(draw, (margin, y), median_line, section_font, (30, 38, 48))
        y += section_header

        for index, measurement in enumerate(summary.measurements):
            col = index % columns
            row = index // columns
            x = margin + col * (tile_width + gap)
            tile_y = y + row * (tile_height + gap)
            draw_tile(
                draw,
                x,
                tile_y,
                tile_width,
                tile_height,
                measurement,
                summary,
                glyph_font,
                label_font,
                small_font,
                threshold_units,
                threshold_ratio,
                include_horizontal,
            )

        rows = math.ceil(len(summary.measurements) / columns)
        y += rows * (tile_height + gap) + 22

    image.save(image_path)


def main() -> None:
    args = parse_args()
    font_path = resolve_path(args.font)
    image_path = resolve_path(args.output_image)
    report_path = resolve_path(args.report)

    summaries = analyze_font(font_path, args.flatten_steps)
    write_report(
        report_path,
        font_path,
        summaries,
        args.threshold_units,
        args.threshold_ratio,
        args.include_horizontal,
    )
    write_image(
        image_path,
        font_path,
        summaries,
        args.threshold_units,
        args.threshold_ratio,
        args.include_horizontal,
    )

    possible = outlier_lines(
        summaries,
        args.threshold_units,
        args.threshold_ratio,
        include_horizontal=args.include_horizontal,
    )
    print(f"Wrote image: {image_path}")
    print(f"Wrote report: {report_path}")
    print(f"Possible inconsistencies: {len(possible)}")
    for line in possible[:20]:
        print(f"- {line}")
    if len(possible) > 20:
        print(f"- ... {len(possible) - 20} more")


if __name__ == "__main__":
    main()
