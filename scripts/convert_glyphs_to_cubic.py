#!/usr/bin/env python3
"""Convert quadratic Glyphs outlines to cubic Bezier outlines.

The default writes a generated cubic .glyphs file under build/ so the original
source remains untouched. Pass --in-place only after reviewing the generated
file in a font editor.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from glyphsLib import GSFont
from glyphsLib.classes import CURVE, LINE, OFFCURVE, QCURVE, GSNode, GSPath


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "sources/GothicGumdrop-Regular.glyphs"
DEFAULT_OUTPUT = REPO_ROOT / "build/GothicGumdrop-Regular.cubic.glyphs"


@dataclass(frozen=True)
class CubicSegment:
    first_control: tuple[float, float]
    second_control: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class LineSegment:
    end: tuple[float, float]


Segment = CubicSegment | LineSegment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert quadratic and off-curve Glyphs contours to cubic curve "
            "nodes. Lines and components are preserved."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Input .glyphs file. Defaults to {DEFAULT_SOURCE.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output .glyphs file. Defaults to {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the input file instead of writing a generated copy.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=3,
        help="Decimal places for generated control points. Defaults to 3.",
    )
    parser.add_argument(
        "--no-smooth-inference",
        action="store_true",
        help="Do not infer smooth flags for generated cubic on-curve nodes.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def clean_number(value: float, precision: int) -> int | float:
    rounded = round(float(value), precision)
    if rounded == 0:
        return 0
    if rounded.is_integer():
        return int(rounded)
    return rounded


def clean_point(point: tuple[float, float], precision: int) -> tuple[int | float, int | float]:
    return clean_number(point[0], precision), clean_number(point[1], precision)


def node_point(node: GSNode) -> tuple[float, float]:
    return float(node.position.x), float(node.position.y)


def midpoint(first: tuple[float, float], second: tuple[float, float]) -> tuple[float, float]:
    return (first[0] + second[0]) / 2, (first[1] + second[1]) / 2


def quadratic_to_cubic(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    first_control = (
        start[0] + (2 / 3) * (control[0] - start[0]),
        start[1] + (2 / 3) * (control[1] - start[1]),
    )
    second_control = (
        end[0] + (2 / 3) * (control[0] - end[0]),
        end[1] + (2 / 3) * (control[1] - end[1]),
    )
    return first_control, second_control, end


def add_quadratic_segments(
    segments: list[Segment],
    start: tuple[float, float],
    controls: list[tuple[float, float]],
    end: tuple[float, float],
) -> tuple[float, float]:
    if not controls:
        segments.append(LineSegment(end))
        return end

    segment_start = start
    for index, control in enumerate(controls):
        segment_end = midpoint(control, controls[index + 1]) if index < len(controls) - 1 else end
        first_control, second_control, on_curve = quadratic_to_cubic(
            segment_start,
            control,
            segment_end,
        )
        segments.append(CubicSegment(first_control, second_control, on_curve))
        segment_start = segment_end
    return end


def iter_paths(font: GSFont) -> Iterable[GSPath]:
    for glyph in font.glyphs:
        for layer in glyph.layers:
            yield from layer.paths


def node_counts(font: GSFont) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in iter_paths(font):
        for node in path.nodes:
            counts[node.type] += 1
    return counts


def angle_delta_degrees(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_angle = math.degrees(math.atan2(first[1], first[0]))
    second_angle = math.degrees(math.atan2(second[1], second[0]))
    return abs((first_angle - second_angle + 180) % 360 - 180)


def nodes_between_cyclic(nodes: list[GSNode], start: int, end: int) -> list[GSNode]:
    collected: list[GSNode] = []
    index = (start + 1) % len(nodes)
    while index != end:
        collected.append(nodes[index])
        index = (index + 1) % len(nodes)
    return collected


def all_offcurve_segments(nodes: list[GSNode]) -> list[Segment]:
    controls = [node_point(node) for node in nodes]
    if len(controls) < 2:
        return []

    segments: list[Segment] = []
    start = midpoint(controls[-1], controls[0])
    current = start
    for index, control in enumerate(controls):
        end = midpoint(control, controls[(index + 1) % len(controls)])
        first_control, second_control, on_curve = quadratic_to_cubic(current, control, end)
        segments.append(CubicSegment(first_control, second_control, on_curve))
        current = end
    return segments


def closed_path_segments(path: GSPath) -> list[Segment]:
    nodes = list(path.nodes)
    if not nodes:
        return []

    oncurve_indices = [
        index for index, node in enumerate(nodes) if node.type in {LINE, QCURVE, CURVE}
    ]
    if not oncurve_indices:
        return all_offcurve_segments(nodes)

    segments: list[Segment] = []
    for index, end_index in enumerate(oncurve_indices):
        start_index = oncurve_indices[index - 1]
        start = node_point(nodes[start_index])
        end_node = nodes[end_index]
        end = node_point(end_node)
        pending = [
            node_point(node)
            for node in nodes_between_cyclic(nodes, start_index, end_index)
            if node.type == OFFCURVE
        ]

        if end_node.type == CURVE:
            if len(pending) == 2:
                segments.append(CubicSegment(pending[0], pending[1], end))
            else:
                add_quadratic_segments(segments, start, pending, end)
        elif end_node.type == QCURVE or pending:
            # Some source contours contain a line node after off-curves. That
            # is illegal as a line segment, but it has a clear quadratic
            # interpretation: the line node is the on-curve endpoint.
            add_quadratic_segments(segments, start, pending, end)
        else:
            segments.append(LineSegment(end))

    return segments


def open_path_segments(path: GSPath) -> tuple[tuple[float, float] | None, list[Segment]]:
    nodes = list(path.nodes)
    if not nodes:
        return None, []

    first_oncurve_index = next(
        (index for index, node in enumerate(nodes) if node.type in {LINE, QCURVE, CURVE}),
        None,
    )
    if first_oncurve_index is None:
        return None, all_offcurve_segments(nodes)

    start = node_point(nodes[first_oncurve_index])
    current = start
    pending: list[tuple[float, float]] = []
    segments: list[Segment] = []

    for node in nodes[first_oncurve_index + 1 :]:
        if node.type == OFFCURVE:
            pending.append(node_point(node))
            continue

        end = node_point(node)
        if node.type == CURVE and len(pending) == 2:
            segments.append(CubicSegment(pending[0], pending[1], end))
        elif node.type == LINE and not pending:
            segments.append(LineSegment(end))
        else:
            add_quadratic_segments(segments, current, pending, end)
        current = end
        pending = []

    return start, segments


def infer_smooth_nodes(path: GSPath, tolerance_degrees: float = 6.0) -> None:
    nodes = list(path.nodes)
    if len(nodes) < 3:
        return

    for node in nodes:
        node.smooth = False

    for index, node in enumerate(nodes):
        if node.type != CURVE:
            continue

        prev_node = nodes[index - 1]
        next_node = nodes[(index + 1) % len(nodes)]
        if prev_node.type != OFFCURVE or next_node.type != OFFCURVE:
            continue

        incoming = (
            node.position.x - prev_node.position.x,
            node.position.y - prev_node.position.y,
        )
        outgoing = (
            next_node.position.x - node.position.x,
            next_node.position.y - node.position.y,
        )
        if incoming == (0, 0) or outgoing == (0, 0):
            continue
        if angle_delta_degrees(incoming, outgoing) <= tolerance_degrees:
            node.smooth = True


def path_to_cubic(path: GSPath, precision: int, infer_smooth: bool) -> GSPath:
    nodes: list[GSNode] = []
    closed = bool(path.closed)
    if closed:
        start = None
        segments = closed_path_segments(path)
    else:
        start, segments = open_path_segments(path)
        if start is not None:
            nodes.append(GSNode(clean_point(start, precision), LINE))

    for segment in segments:
        if isinstance(segment, LineSegment):
            nodes.append(GSNode(clean_point(segment.end, precision), LINE))
            continue

        nodes.append(GSNode(clean_point(segment.first_control, precision), OFFCURVE))
        nodes.append(GSNode(clean_point(segment.second_control, precision), OFFCURVE))
        nodes.append(GSNode(clean_point(segment.end, precision), CURVE))

    new_path = GSPath()
    new_path.closed = closed
    new_path.nodes = nodes
    if infer_smooth:
        infer_smooth_nodes(new_path)
    return new_path


def convert_font(font: GSFont, precision: int, infer_smooth: bool) -> int:
    converted_paths = 0
    for path in iter_paths(font):
        if not any(node.type in {OFFCURVE, QCURVE, CURVE} for node in path.nodes):
            continue

        cubic_path = path_to_cubic(path, precision, infer_smooth)
        path.closed = cubic_path.closed
        path.nodes = list(cubic_path.nodes)
        converted_paths += 1
    return converted_paths


def main() -> None:
    args = parse_args()
    source = resolve_path(args.source)
    output = source if args.in_place else resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    font = GSFont(str(source))
    before = node_counts(font)
    converted_paths = convert_font(
        font,
        precision=args.precision,
        infer_smooth=not args.no_smooth_inference,
    )
    after = node_counts(font)

    if after[QCURVE]:
        raise SystemExit(f"Conversion incomplete: {after[QCURVE]} qcurve nodes remain")

    font.save(str(output))

    print(f"Read: {source}")
    print(f"Wrote: {output}")
    print(f"Converted paths: {converted_paths}")
    print(f"qcurve nodes: {before[QCURVE]} -> {after[QCURVE]}")
    print(f"curve nodes: {before[CURVE]} -> {after[CURVE]}")


if __name__ == "__main__":
    main()
