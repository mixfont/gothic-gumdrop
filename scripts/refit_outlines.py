#!/usr/bin/env python3
"""Re-fit Glyphs outlines as clean cubic Beziers.

Unlike convert_glyphs_to_cubic.py (an exact quadratic->cubic lift that keeps
every segment), this tool re-draws each contour from scratch:

1. Flatten the contour to a dense polyline.
2. Detect corners from tangent discontinuities.
3. Fit each corner-to-corner run with as few cubic segments as possible
   (Schneider curve-fitting), which smooths autotrace wobble.
4. Insert on-curve points at horizontal/vertical extrema (GF outline guide).
5. Guardrail: reject any contour whose refit deviates beyond --max-deviation
   font units from the original polyline; the original is kept in that case.

Writes a cubic .glyphs file (default build/GothicGumdrop-Regular.cubic.glyphs).
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

from glyphsLib import GSFont
from glyphsLib.classes import CURVE, LINE, OFFCURVE, GSNode, GSPath

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "sources/GothicGumdrop-Regular.glyphs"
DEFAULT_OUTPUT = REPO_ROOT / "build/GothicGumdrop-Regular.cubic.glyphs"

Point = tuple[float, float]


# ---------------------------------------------------------------- geometry

def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def scale(a: Point, s: float) -> Point:
    return (a[0] * s, a[1] * s)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def normalize(a: Point) -> Point:
    n = norm(a)
    if n == 0:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def cubic_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def quad_point(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    mt = 1 - t
    return (
        mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
        mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
    )


# ------------------------------------------------- flatten quadratic paths

def flatten_glyphs_path(path: GSPath, steps: int = 24) -> list[Point]:
    """Flatten a (possibly quadratic) GSPath to a dense closed polyline."""
    nodes = list(path.nodes)
    if not nodes:
        return []

    pts = [(float(n.position.x), float(n.position.y)) for n in nodes]
    kinds = [n.type for n in nodes]

    # Rotate so we start at an on-curve node.
    first_on = next((i for i, k in enumerate(kinds) if k != OFFCURVE), None)
    poly: list[Point] = []

    if first_on is None:
        # TrueType-style all-off-curve contour: implied on-curves at midpoints.
        n = len(pts)
        for i in range(n):
            p_prev = pts[i - 1]
            p = pts[i]
            p_next = pts[(i + 1) % n]
            start = lerp(p_prev, p, 0.5)
            end = lerp(p, p_next, 0.5)
            for s in range(steps):
                poly.append(quad_point(start, p, end, s / steps))
        return poly

    order = list(range(first_on, len(nodes))) + list(range(0, first_on))
    pts = [pts[i] for i in order]
    kinds = [kinds[i] for i in order]

    current = pts[0]
    poly.append(current)
    pending: list[Point] = []
    seq = list(zip(pts[1:] + pts[:1], kinds[1:] + kinds[:1]))
    for p, kind in seq:
        if kind == OFFCURVE:
            pending.append(p)
            continue
        if not pending:
            poly.append(p)
        elif kind == CURVE and len(pending) == 2:
            for s in range(1, steps + 1):
                poly.append(cubic_point(current, pending[0], pending[1], p, s / steps))
        else:
            # Quadratic run with implied on-curve midpoints.
            seg_start = current
            for i, ctrl in enumerate(pending):
                seg_end = lerp(ctrl, pending[i + 1], 0.5) if i < len(pending) - 1 else p
                for s in range(1, steps + 1):
                    poly.append(quad_point(seg_start, ctrl, seg_end, s / steps))
                seg_start = seg_end
        current = p
        pending = []

    if poly and norm(sub(poly[0], poly[-1])) < 1e-6:
        poly.pop()
    return poly


def resample(poly: list[Point], spacing: float = 3.0) -> list[Point]:
    """Resample closed polyline at roughly uniform arc-length spacing."""
    if len(poly) < 3:
        return poly
    out = [poly[0]]
    carry = 0.0
    n = len(poly)
    for i in range(1, n + 1):
        a = poly[i - 1]
        b = poly[i % n]
        seg = norm(sub(b, a))
        if seg == 0:
            continue
        t = (spacing - carry) / seg
        while t <= 1.0:
            out.append(lerp(a, b, t))
            t += spacing / seg
        carry = (carry + seg) % spacing
    if len(out) > 1 and norm(sub(out[0], out[-1])) < spacing * 0.5:
        out.pop()
    return out


# ---------------------------------------------------------- corner finding

def path_corner_points(path: GSPath, angle_threshold_deg: float) -> list[Point]:
    """Corners straight from the source structure: on-curve nodes whose
    incoming/outgoing tangents break by more than the threshold."""
    nodes = list(path.nodes)
    n = len(nodes)
    if n < 3:
        return []
    corners: list[Point] = []
    for i, node in enumerate(nodes):
        if node.type == OFFCURVE:
            continue
        p = (float(node.position.x), float(node.position.y))
        prev_n = nodes[(i - 1) % n]
        next_n = nodes[(i + 1) % n]
        v_in = sub(p, (float(prev_n.position.x), float(prev_n.position.y)))
        v_out = sub((float(next_n.position.x), float(next_n.position.y)), p)
        if norm(v_in) == 0 or norm(v_out) == 0:
            continue
        cosv = max(-1.0, min(1.0, dot(normalize(v_in), normalize(v_out))))
        if math.degrees(math.acos(cosv)) >= angle_threshold_deg:
            corners.append(p)
    return corners


def nearest_index(poly: list[Point], p: Point) -> int:
    best_i = 0
    best_d = float("inf")
    for i, q in enumerate(poly):
        d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def smooth_run(run: list[Point], window: int, passes: int = 2) -> list[Point]:
    """Moving-average smooth an open run, keeping the endpoints pinned."""
    if len(run) < 2 * window + 3 or window < 1:
        return run
    out = list(run)
    for _ in range(passes):
        smoothed = [out[0]]
        for i in range(1, len(out) - 1):
            lo = max(0, i - window)
            hi = min(len(out) - 1, i + window)
            pts = out[lo : hi + 1]
            smoothed.append(
                (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            )
        smoothed.append(out[-1])
        out = smoothed
    return out


def find_curvature_corners(poly: list[Point], spacing: float,
                           window_units: float = 13.0,
                           turn_threshold_deg: float = 60.0) -> list[int]:
    """Soft corners: places where a lot of turning concentrates in a short
    arc (tight corner arcs in a rounded design). Returns peak indices."""
    n = len(poly)
    if n < 8:
        return []
    turns = []
    for i in range(n):
        v_in = sub(poly[i], poly[(i - 1) % n])
        v_out = sub(poly[(i + 1) % n], poly[i])
        if norm(v_in) == 0 or norm(v_out) == 0:
            turns.append(0.0)
            continue
        cosv = max(-1.0, min(1.0, dot(normalize(v_in), normalize(v_out))))
        turns.append(math.degrees(math.acos(cosv)))
    half = max(1, int(round(window_units / spacing / 2)))
    windowed = []
    for i in range(n):
        windowed.append(sum(turns[(i + k) % n] for k in range(-half, half + 1)))
    corners = []
    min_sep = 2 * half + 1
    for i in range(n):
        w = windowed[i]
        if w < turn_threshold_deg:
            continue
        if all(w >= windowed[(i + k) % n] for k in range(-min_sep, min_sep + 1)):
            corners.append(i)
    # enforce separation (cyclic)
    filtered: list[int] = []
    for i in corners:
        if filtered and (i - filtered[-1]) % n < min_sep:
            continue
        filtered.append(i)
    if len(filtered) > 1 and (filtered[0] - filtered[-1]) % n < min_sep:
        filtered.pop()
    return filtered


# ----------------------------------------------- Schneider cubic fitting

def fit_cubic(points: list[Point], t_hat1: Point, t_hat2: Point, error: float,
              depth: int = 0) -> list[tuple[Point, Point, Point, Point]]:
    """Fit one run of points with cubics (Philip J. Schneider, Graphics Gems)."""
    if len(points) == 2:
        dist = norm(sub(points[1], points[0])) / 3.0
        return [(
            points[0],
            add(points[0], scale(t_hat1, dist)),
            add(points[1], scale(t_hat2, dist)),
            points[1],
        )]

    u = chord_length_parameterize(points)
    bez = generate_bezier(points, u, t_hat1, t_hat2)
    max_err, split = compute_max_error(points, bez, u)
    if max_err < error:
        return [bez]

    # Try reparameterization a few times.
    if max_err < error * error:
        for _ in range(4):
            u = reparameterize(points, u, bez)
            bez = generate_bezier(points, u, t_hat1, t_hat2)
            max_err, split = compute_max_error(points, bez, u)
            if max_err < error:
                return [bez]

    if depth > 24:
        return [bez]

    center_tangent = normalize(sub(points[split - 1], points[split + 1]))
    if center_tangent == (0.0, 0.0):
        center_tangent = normalize(sub(points[split - 1], points[split]))
    left = fit_cubic(points[: split + 1], t_hat1, center_tangent, error, depth + 1)
    right = fit_cubic(points[split:], scale(center_tangent, -1.0), t_hat2, error, depth + 1)
    return left + right


def chord_length_parameterize(points: list[Point]) -> list[float]:
    u = [0.0]
    for i in range(1, len(points)):
        u.append(u[i - 1] + norm(sub(points[i], points[i - 1])))
    total = u[-1] or 1.0
    return [x / total for x in u]


def generate_bezier(points: list[Point], u: list[float], t_hat1: Point,
                    t_hat2: Point) -> tuple[Point, Point, Point, Point]:
    n = len(points)
    first, last = points[0], points[-1]

    c00 = c01 = c11 = 0.0
    x0 = x1 = 0.0
    for i in range(n):
        t = u[i]
        mt = 1 - t
        b0 = mt * mt * mt
        b1 = 3 * t * mt * mt
        b2 = 3 * t * t * mt
        b3 = t * t * t
        a1 = scale(t_hat1, b1)
        a2 = scale(t_hat2, b2)
        c00 += dot(a1, a1)
        c01 += dot(a1, a2)
        c11 += dot(a2, a2)
        tmp = sub(points[i], add(scale(first, b0 + b1), scale(last, b2 + b3)))
        x0 += dot(a1, tmp)
        x1 += dot(a2, tmp)

    det_c0_c1 = c00 * c11 - c01 * c01
    det_c0_x = c00 * x1 - c01 * x0
    det_x_c1 = x0 * c11 - x1 * c01
    alpha_l = 0.0 if det_c0_c1 == 0 else det_x_c1 / det_c0_c1
    alpha_r = 0.0 if det_c0_c1 == 0 else det_c0_x / det_c0_c1

    seg_length = norm(sub(last, first))
    epsilon = 1e-6 * seg_length
    if alpha_l < epsilon or alpha_r < epsilon:
        dist = seg_length / 3.0
        alpha_l = alpha_r = dist

    return (
        first,
        add(first, scale(t_hat1, alpha_l)),
        add(last, scale(t_hat2, alpha_r)),
        last,
    )


def reparameterize(points: list[Point], u: list[float],
                   bez: tuple[Point, Point, Point, Point]) -> list[float]:
    return [newton_raphson(bez, points[i], u[i]) for i in range(len(points))]


def newton_raphson(bez, point: Point, u: float) -> float:
    p0, p1, p2, p3 = bez
    d = sub(cubic_point(p0, p1, p2, p3, u), point)
    # derivative control points
    q1 = [scale(sub(p1, p0), 3), scale(sub(p2, p1), 3), scale(sub(p3, p2), 3)]
    q2 = [scale(sub(q1[1], q1[0]), 2), scale(sub(q1[2], q1[1]), 2)]
    d1 = quad_point(q1[0], q1[1], q1[2], u)
    d2 = lerp(q2[0], q2[1], u)
    numerator = dot(d, d1)
    denominator = dot(d1, d1) + dot(d, d2)
    if denominator == 0:
        return u
    return min(1.0, max(0.0, u - numerator / denominator))


def compute_max_error(points: list[Point], bez, u: list[float]) -> tuple[float, int]:
    max_dist = 0.0
    split = len(points) // 2
    p0, p1, p2, p3 = bez
    for i in range(1, len(points) - 1):
        dist = norm(sub(cubic_point(p0, p1, p2, p3, u[i]), points[i]))
        if dist > max_dist:
            max_dist = dist
            split = i
    return max_dist * max_dist, split


# ------------------------------------------------------- extrema insertion

def split_cubic(bez, t: float):
    p0, p1, p2, p3 = bez
    p01 = lerp(p0, p1, t)
    p12 = lerp(p1, p2, t)
    p23 = lerp(p2, p3, t)
    p012 = lerp(p01, p12, t)
    p123 = lerp(p12, p23, t)
    mid = lerp(p012, p123, t)
    return (p0, p01, p012, mid), (mid, p123, p23, p3)


def extrema_ts(bez) -> list[float]:
    p0, p1, p2, p3 = bez
    ts = []
    for axis in (0, 1):
        a = 3 * (-p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis])
        b = 6 * (p0[axis] - 2 * p1[axis] + p2[axis])
        c = 3 * (p1[axis] - p0[axis])
        if abs(a) < 1e-12:
            if abs(b) > 1e-12:
                t = -c / b
                if 0.02 < t < 0.98:
                    ts.append(t)
            continue
        disc = b * b - 4 * a * c
        if disc < 0:
            continue
        sq = math.sqrt(disc)
        for t in ((-b + sq) / (2 * a), (-b - sq) / (2 * a)):
            if 0.02 < t < 0.98:
                ts.append(t)
    return sorted(set(ts))


def insert_extrema(beziers, min_significance: float = 3.0):
    out = []
    for bez in beziers:
        ts = extrema_ts(bez)
        # Only keep extrema that stick out meaningfully: the extremum must be
        # at least min_significance units beyond both segment endpoints on
        # its axis, otherwise a point there is clutter, not structure.
        significant = []
        p0, p3 = bez[0], bez[3]
        for t in ts:
            pt = cubic_point(*bez, t)
            for axis in (0, 1):
                lo = min(p0[axis], p3[axis])
                hi = max(p0[axis], p3[axis])
                if pt[axis] < lo - min_significance or pt[axis] > hi + min_significance:
                    significant.append(t)
                    break
        ts = significant
        if not ts:
            out.append(bez)
            continue
        rest = bez
        prev_t = 0.0
        for t in ts:
            local = (t - prev_t) / (1 - prev_t) if prev_t < 1 else 0
            left, rest = split_cubic(rest, local)
            out.append(left)
            prev_t = t
        out.append(rest)
    return out


def chord(bez) -> float:
    return norm(sub(bez[3], bez[0]))


def merge_tiny_segments(beziers, max_err: float = 2.5, tiny: float = 18.0):
    """Merge adjacent cubic pairs where one is a sliver, if a single cubic
    reproduces both within max_err. Kills untidy short segments at joints."""
    beziers = list(beziers)
    changed = True
    while changed and len(beziers) > 1:
        changed = False
        for i in range(len(beziers) - 1):
            b1, b2 = beziers[i], beziers[i + 1]
            if chord(b1) >= tiny and chord(b2) >= tiny:
                continue
            pts = [cubic_point(*b1, t / 12) for t in range(13)]
            pts += [cubic_point(*b2, t / 12) for t in range(1, 13)]
            t1 = normalize(sub(b1[1], b1[0])) if b1[1] != b1[0] else normalize(sub(b1[3], b1[0]))
            t2 = normalize(sub(b2[2], b2[3])) if b2[2] != b2[3] else normalize(sub(b2[0], b2[3]))
            fitted = fit_cubic(pts, t1, t2, max_err * max_err)
            if len(fitted) == 1:
                beziers[i : i + 2] = fitted
                changed = True
                break
    return beziers


def snap_semi_axis_lines(nodes: list[GSNode], max_offset: float = 4.0,
                         min_length: float = 80.0) -> None:
    """Make almost-vertical/horizontal long lines exactly axis-aligned."""
    n = len(nodes)
    for i, node in enumerate(nodes):
        if node.type != LINE:
            continue
        prev_n = nodes[(i - 1) % n]
        if prev_n.type == OFFCURVE:
            continue
        dx = node.position.x - prev_n.position.x
        dy = node.position.y - prev_n.position.y
        if abs(dy) >= min_length and 0 < abs(dx) <= max_offset:
            x = round((node.position.x + prev_n.position.x) / 2, 1)
            node.position = (x, node.position.y)
            prev_n.position = (x, prev_n.position.y)
        elif abs(dx) >= min_length and 0 < abs(dy) <= max_offset:
            y = round((node.position.y + prev_n.position.y) / 2, 1)
            node.position = (node.position.x, y)
            prev_n.position = (prev_n.position.x, y)


# ------------------------------------------------------------- refit paths

@dataclass
class RefitStats:
    paths_refit: int = 0
    paths_kept: int = 0
    nodes_before: int = 0
    nodes_after: int = 0
    worst_deviation: float = 0.0


def polyline_deviation(poly: list[Point], beziers) -> float:
    """Max distance from original polyline samples to the refit curve,
    measured against the flattened curve as a chain of segments."""
    samples: list[Point] = []
    for bez in beziers:
        p0, p1, p2, p3 = bez
        for s in range(16):
            samples.append(cubic_point(p0, p1, p2, p3, s / 16))
    if len(samples) < 2:
        return float("inf")
    samples.append(samples[0])

    def seg_dist_sq(p: Point, a: Point, b: Point) -> float:
        ab = sub(b, a)
        denom = dot(ab, ab)
        t = 0.0 if denom == 0 else max(0.0, min(1.0, dot(sub(p, a), ab) / denom))
        proj = add(a, scale(ab, t))
        dv = sub(p, proj)
        return dot(dv, dv)

    worst = 0.0
    step = max(1, len(poly) // 200)
    for i in range(0, len(poly), step):
        p = poly[i]
        best = min(seg_dist_sq(p, samples[j], samples[j + 1])
                   for j in range(len(samples) - 1))
        worst = max(worst, best)
    return math.sqrt(worst)


def is_line_run(points: list[Point], tolerance: float = 0.75) -> bool:
    if len(points) < 2:
        return True
    a, b = points[0], points[-1]
    ab = sub(b, a)
    length = norm(ab)
    if length == 0:
        return False
    for p in points[1:-1]:
        # perpendicular distance to chord
        t = dot(sub(p, a), ab) / (length * length)
        proj = add(a, scale(ab, max(0.0, min(1.0, t))))
        if norm(sub(p, proj)) > tolerance:
            return False
    return True


def refit_path(path: GSPath, fit_error: float, corner_angle: float,
               max_deviation: float, resample_spacing: float) -> tuple[GSPath | None, float]:
    """Try heavy smoothing first (best wobble removal); if the result drifts
    past the guardrail, fall back to lighter smoothing before giving up."""
    best: tuple[GSPath | None, float] = (None, float("inf"))
    for window, passes, err in ((4, 3, fit_error), (2, 2, fit_error * 0.7),
                                (1, 1, fit_error * 0.5)):
        refit, deviation = _refit_path_once(
            path, err, corner_angle, max_deviation, resample_spacing,
            smooth_window=window, smooth_passes=passes,
        )
        if refit is not None:
            return refit, deviation
        if deviation < best[1]:
            best = (None, deviation)
    return best


def _refit_path_once(path: GSPath, fit_error: float, corner_angle: float,
                     max_deviation: float, resample_spacing: float,
                     smooth_window: int, smooth_passes: int) -> tuple[GSPath | None, float]:
    poly = flatten_glyphs_path(path)
    if len(poly) < 8:
        return None, 0.0
    dense = resample(poly, resample_spacing)
    if len(dense) < 8:
        return None, 0.0
    corner_pts = path_corner_points(path, corner_angle)
    structural = {nearest_index(dense, p) for p in corner_pts}
    soft = set(find_curvature_corners(dense, resample_spacing))
    # Structural corners win; drop soft corners too close to a structural one.
    n = len(dense)
    min_sep = max(2, int(round(9.0 / resample_spacing)))
    soft = {
        s for s in soft
        if all(min((s - c) % n, (c - s) % n) >= min_sep for c in structural)
    }
    corners = sorted(structural | soft)
    if not corners:
        corners = [0]

    node_runs: list[tuple[list, bool]] = []  # (beziers or line end, is_line)
    for ci, start_idx in enumerate(corners):
        end_idx = corners[(ci + 1) % len(corners)]
        if end_idx > start_idx:
            run = dense[start_idx : end_idx + 1]
        else:
            run = dense[start_idx:] + dense[: end_idx + 1]
        if len(run) < 2:
            continue
        run = smooth_run(run, window=smooth_window, passes=smooth_passes)
        if is_line_run(run, tolerance=1.5):
            node_runs.append(([run[0], run[-1]], True))
            continue
        k = min(3, len(run) - 1)
        t1 = normalize(sub(run[k], run[0]))
        t2 = normalize(sub(run[-1 - k], run[-1]))
        fitted = fit_cubic(run, t1, t2, fit_error * fit_error)
        fitted = insert_extrema(fitted)
        fitted = merge_tiny_segments(fitted)
        node_runs.append((fitted, False))

    # Deviation guardrail against the *original* polyline.
    all_beziers = []
    for run, is_line in node_runs:
        if is_line:
            a, b = run
            all_beziers.append((a, lerp(a, b, 1 / 3), lerp(a, b, 2 / 3), b))
        else:
            all_beziers.extend(run)
    deviation = polyline_deviation(dense, all_beziers)
    if deviation > max_deviation:
        return None, deviation

    # Build the new GSPath.
    nodes: list[GSNode] = []

    def rp(p: Point) -> tuple[float, float]:
        return (round(p[0], 1), round(p[1], 1))

    for run, is_line in node_runs:
        if is_line:
            nodes.append(GSNode(rp(run[1]), LINE))
        else:
            for bez in run:
                _, c1, c2, end = bez
                nodes.append(GSNode(rp(c1), OFFCURVE))
                nodes.append(GSNode(rp(c2), OFFCURVE))
                nodes.append(GSNode(rp(end), CURVE))

    if len(nodes) < 3:
        return None, deviation

    snap_semi_axis_lines(nodes)

    new_path = GSPath()
    new_path.closed = True
    new_path.nodes = nodes

    # Smooth flags: mark curve joints whose tangents are continuous.
    nds = list(new_path.nodes)
    for i, node in enumerate(nds):
        if node.type not in (CURVE, LINE):
            continue
        prev_n = nds[i - 1]
        next_n = nds[(i + 1) % len(nds)]
        if prev_n.type != OFFCURVE or next_n.type != OFFCURVE:
            continue
        v_in = (node.position.x - prev_n.position.x, node.position.y - prev_n.position.y)
        v_out = (next_n.position.x - node.position.x, next_n.position.y - node.position.y)
        if norm(v_in) == 0 or norm(v_out) == 0:
            continue
        cosv = max(-1.0, min(1.0, dot(normalize(v_in), normalize(v_out))))
        if math.degrees(math.acos(cosv)) <= 8.0:
            node.smooth = True

    return new_path, deviation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fit-error", type=float, default=2.0,
                        help="Schneider fitting error in font units (default 2.0)")
    parser.add_argument("--corner-angle", type=float, default=32.0,
                        help="Tangent break angle treated as a corner (default 32)")
    parser.add_argument("--max-deviation", type=float, default=5.0,
                        help="Reject refit contours deviating more than this (default 5.0)")
    parser.add_argument("--resample-spacing", type=float, default=3.0)
    parser.add_argument("--glyphs", nargs="*", help="Only refit these glyph names")
    args = parser.parse_args()

    font = GSFont(str(args.source))
    stats = RefitStats()
    kept_glyphs = []

    for glyph in font.glyphs:
        if args.glyphs and glyph.name not in args.glyphs:
            continue
        for layer in glyph.layers:
            new_paths = []
            for path in layer.paths:
                stats.nodes_before += len(path.nodes)
                refit, deviation = refit_path(
                    path, args.fit_error, args.corner_angle,
                    args.max_deviation, args.resample_spacing,
                )
                stats.worst_deviation = max(stats.worst_deviation, deviation)
                if refit is None:
                    new_paths.append(path)
                    stats.paths_kept += 1
                    stats.nodes_after += len(path.nodes)
                    if len(path.nodes) >= 8:
                        kept_glyphs.append((glyph.name, deviation))
                else:
                    new_paths.append(refit)
                    stats.paths_refit += 1
                    stats.nodes_after += len(refit.nodes)
            # replace paths, keep components untouched
            components = [s for s in layer.shapes if not isinstance(s, GSPath)]
            layer.shapes = components + new_paths

    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(args.output))

    print(f"Refit paths:   {stats.paths_refit}")
    print(f"Kept original: {stats.paths_kept}")
    print(f"Nodes: {stats.nodes_before} -> {stats.nodes_after} "
          f"({100 * stats.nodes_after / max(1, stats.nodes_before):.0f}%)")
    if kept_glyphs:
        print("Contours kept due to deviation guardrail:")
        for name, deviation in kept_glyphs[:20]:
            print(f"  {name}: deviation {deviation:.1f}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
