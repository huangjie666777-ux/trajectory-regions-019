"""Core trajectory/region crossing analysis using Shapely 2.

All coordinates are planar metric units. The boundary of a region is treated
as outside the region: touching a vertex or moving along an edge does not
count as dwelling inside.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

EPS = 1e-9


class AnalysisError(ValueError):
    """Raised for invalid region or trajectory input."""


@dataclass
class TrajectoryPoint:
    x: float
    y: float
    time: datetime


@dataclass
class Interval:
    start: datetime
    end: datetime
    truncated_start: bool = False
    truncated_end: bool = False

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class RegionResult:
    region_id: str
    intervals: list[Interval] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(iv.seconds for iv in self.intervals)


def _check_finite(coords, label: str) -> None:
    for i, c in enumerate(coords):
        if len(c) != 2 or not all(math.isfinite(v) for v in c):
            raise AnalysisError(
                f"{label}: coordinate at index {i} is not a finite [x, y] pair"
            )


def _normalize_ring(coords, label: str) -> list[tuple[float, float]]:
    _check_finite(coords, label)
    ring = [(float(x), float(y)) for x, y in coords]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise AnalysisError(f"{label}: ring needs at least 3 distinct positions")
    if len(set(ring)) < 3:
        raise AnalysisError(f"{label}: ring has fewer than 3 distinct positions")
    return ring


def build_region_polygon(region_id: str, outer, holes) -> Polygon:
    label = f"region '{region_id}'"
    shell = _normalize_ring(outer, f"{label} outer ring")
    hole_rings = [
        _normalize_ring(h, f"{label} hole {i}") for i, h in enumerate(holes or [])
    ]
    poly = Polygon(shell, hole_rings)
    if poly.is_empty or not poly.is_valid:
        raise AnalysisError(
            f"{label}: invalid polygon (self-intersecting ring, hole outside "
            f"outer ring, or overlapping holes)"
        )
    return poly


def validate_trajectory(points: list[TrajectoryPoint]) -> None:
    if len(points) < 2:
        raise AnalysisError("trajectory: at least 2 points are required")
    for i, p in enumerate(points):
        if not (math.isfinite(p.x) and math.isfinite(p.y)):
            raise AnalysisError(f"trajectory point {i}: coordinates must be finite")
        if p.time.tzinfo is None or p.time.tzinfo.utcoffset(p.time) is None:
            raise AnalysisError(
                f"trajectory point {i}: timestamp must include a timezone offset"
            )
        if i > 0 and not p.time > points[i - 1].time:
            raise AnalysisError(
                f"trajectory point {i}: timestamps must be strictly increasing"
            )


def _strictly_inside(poly: Polygon, boundary: BaseGeometry, x: float, y: float) -> bool:
    pt = Point(x, y)
    return poly.covers(pt) and not boundary.covers(pt)


def _segment_intervals(
    poly: Polygon,
    boundary: BaseGeometry,
    p0: TrajectoryPoint,
    p1: TrajectoryPoint,
) -> list[tuple[datetime, datetime]]:
    """Time intervals of one segment spent strictly inside the region."""
    t0, t1 = p0.time, p1.time
    total = (t1 - t0).total_seconds()

    if p0.x == p1.x and p0.y == p1.y:
        # Stationary segment: counts only if strictly inside.
        if _strictly_inside(poly, boundary, p0.x, p0.y):
            return [(t0, t1)]
        return []

    seg = LineString([(p0.x, p0.y), (p1.x, p1.y)])
    inter = seg.intersection(poly)

    if inter.is_empty:
        return []
    geoms: list[BaseGeometry] = (
        list(inter.geoms) if hasattr(inter, "geoms") else [inter]
    )

    out: list[tuple[datetime, datetime]] = []
    for g in geoms:
        if g.geom_type not in ("LineString", "LinearRing") or g.length <= EPS:
            continue
        mid = g.interpolate(0.5, normalized=True)
        if not _strictly_inside(poly, boundary, mid.x, mid.y):
            # Lying on the boundary does not count.
            continue
        f0 = seg.project(g.interpolate(0.0, normalized=True)) / seg.length
        f1 = seg.project(g.interpolate(1.0, normalized=True)) / seg.length
        f0, f1 = max(0.0, min(f0, f1)), min(1.0, max(f0, f1))
        out.append(
            (t0 + timedelta(seconds=f0 * total), t0 + timedelta(seconds=f1 * total))
        )
    return out


def analyze_region(
    region_id: str, poly: Polygon, points: list[TrajectoryPoint]
) -> RegionResult:
    boundary = poly.boundary
    raw: list[tuple[datetime, datetime]] = []
    for p0, p1 in zip(points, points[1:]):
        raw.extend(_segment_intervals(poly, boundary, p0, p1))

    raw.sort(key=lambda iv: iv[0])
    merged: list[Interval] = []
    for start, end in raw:
        if merged and start <= merged[-1].end:
            if end > merged[-1].end:
                merged[-1].end = end
        else:
            merged.append(Interval(start, end))

    # Mark truncation when the trajectory starts/ends inside the region.
    if merged:
        first, last = points[0], points[-1]
        if (
            _strictly_inside(poly, boundary, first.x, first.y)
            and merged[0].start == first.time
        ):
            merged[0].truncated_start = True
        if (
            _strictly_inside(poly, boundary, last.x, last.y)
            and merged[-1].end == last.time
        ):
            merged[-1].truncated_end = True

    return RegionResult(region_id=region_id, intervals=merged)
