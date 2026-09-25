"""轨迹穿越区域的核心几何与时间区间计算。

坐标为平面米制，不做经纬度换算。区域内部指多边形内部（不含边界），
孔洞内部不属于区域。相邻轨迹点之间按直线匀速移动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.validation import explain_validity

from .models import AnalyzeRequest, IntervalOut, RegionSummaryOut, TrackPointIn

MERGE_EPS_SECONDS = 1e-6


class InputError(ValueError):
    """请求数据无效，消息中指明对应区域或轨迹点。"""


@dataclass
class RawInterval:
    start: float
    end: float
    start_truncated: bool = False
    end_truncated: bool = False


def _normalize_ring(ring: List[List[float]]) -> List[Tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in ring]
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    return points


def build_region_geometry(region) -> Polygon:
    """校验并构建区域多边形，错误信息包含区域 ID。"""
    rid = region.id
    outer = _normalize_ring(region.outer)
    if len(set(outer)) != len(outer) or len(outer) < 3:
        raise InputError(f"region '{rid}': outer ring has duplicate points or fewer than 3 distinct points")
    outer_poly = Polygon(outer)
    if not outer_poly.is_valid or outer_poly.area <= 0:
        raise InputError(f"region '{rid}': outer ring is not a simple polygon ({explain_validity(outer_poly)})")

    hole_polys = []
    holes = []
    for index, hole in enumerate(region.holes):
        ring = _normalize_ring(hole)
        if len(set(ring)) != len(ring) or len(ring) < 3:
            raise InputError(f"region '{rid}': hole {index} has duplicate points or fewer than 3 distinct points")
        hole_poly = Polygon(ring)
        if not hole_poly.is_valid or hole_poly.area <= 0:
            raise InputError(f"region '{rid}': hole {index} is not a simple polygon ({explain_validity(hole_poly)})")
        if not outer_poly.contains(hole_poly):
            raise InputError(f"region '{rid}': hole {index} is not strictly inside the outer ring")
        for prev in hole_polys:
            if not prev.disjoint(hole_poly):
                raise InputError(f"region '{rid}': hole {index} overlaps or touches another hole")
        hole_polys.append(hole_poly)
        holes.append(ring)

    polygon = Polygon(outer, holes)
    if not polygon.is_valid:
        raise InputError(f"region '{rid}': invalid polygon ({explain_validity(polygon)})")
    return polygon


def validate_track(track: List[TrackPointIn]) -> List[TrackPointIn]:
    for index in range(1, len(track)):
        if not track[index].time > track[index - 1].time:
            raise InputError(f"track point {index}: time must be strictly increasing")
    return track


def _segment_intervals(a, b, t0, t1, polygon) -> List[Tuple[float, float]]:
    """返回单个线段落在区域内部的时间区间（轨迹绝对时间，秒）。"""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        if polygon.contains(Point(a)):
            return [(t0, t1)]
        return []

    segment = LineString([a, b])
    crossing = segment.intersection(polygon)
    if crossing.is_empty:
        return []

    pieces = []
    if crossing.geom_type == "LineString":
        pieces = [crossing]
    elif crossing.geom_type == "MultiLineString":
        pieces = list(crossing.geoms)
    else:
        pieces = [g for g in getattr(crossing, "geoms", []) if g.geom_type == "LineString"]

    length_sq = dx * dx + dy * dy
    duration = t1 - t0
    intervals = []
    for piece in pieces:
        coords = list(piece.coords)
        mid = ((coords[0][0] + coords[-1][0]) / 2.0, (coords[0][1] + coords[-1][1]) / 2.0)
        if not polygon.contains(Point(mid)):
            continue
        fractions = []
        for px, py in (coords[0], coords[-1]):
            s = ((px - a[0]) * dx + (py - a[1]) * dy) / length_sq
            fractions.append(min(1.0, max(0.0, s)))
        s0, s1 = min(fractions), max(fractions)
        if s1 - s0 <= 0.0:
            continue
        intervals.append((t0 + s0 * duration, t0 + s1 * duration))
    return intervals


def _merge(intervals: List[RawInterval]) -> List[RawInterval]:
    intervals.sort(key=lambda iv: iv.start)
    merged: List[RawInterval] = []
    for iv in intervals:
        if merged and iv.start - merged[-1].end <= MERGE_EPS_SECONDS:
            last = merged[-1]
            last.end = max(last.end, iv.end)
            last.end_truncated = last.end_truncated or iv.end_truncated
        else:
            merged.append(RawInterval(iv.start, iv.end, iv.start_truncated, iv.end_truncated))
    return merged


def _region_intervals(polygon, track, times) -> List[RawInterval]:
    raw: List[RawInterval] = []
    for index in range(len(track) - 1):
        a = (track[index].x, track[index].y)
        b = (track[index + 1].x, track[index + 1].y)
        for start, end in _segment_intervals(a, b, times[index], times[index + 1], polygon):
            raw.append(RawInterval(start, end))

    if raw:
        if polygon.contains(Point(track[0].x, track[0].y)):
            raw[0].start_truncated = True
        if polygon.contains(Point(track[-1].x, track[-1].y)):
            raw[-1].end_truncated = True
    return _merge(raw)


def _format(epoch_seconds: float, tz) -> str:
    moment = datetime.fromtimestamp(epoch_seconds, tz=tz)
    return moment.isoformat(timespec="microseconds")


def analyze(request: AnalyzeRequest) -> Tuple[List[IntervalOut], List[RegionSummaryOut]]:
    seen = set()
    for region in request.regions:
        if region.id in seen:
            raise InputError(f"region '{region.id}': duplicate region id")
        seen.add(region.id)

    track = validate_track(request.track)
    times = [point.time.timestamp() for point in track]
    tz = track[0].time.tzinfo

    details: List[IntervalOut] = []
    summaries: List[RegionSummaryOut] = []
    for region in request.regions:
        polygon = build_region_geometry(region)
        intervals = _region_intervals(polygon, track, times)
        total = 0.0
        for iv in intervals:
            stay = round(iv.end - iv.start, 6)
            total += stay
            details.append(IntervalOut(
                region_id=region.id,
                enter=_format(iv.start, tz),
                leave=_format(iv.end, tz),
                stay_seconds=stay,
                start_truncated=iv.start_truncated,
                end_truncated=iv.end_truncated,
            ))
        summaries.append(RegionSummaryOut(
            region_id=region.id,
            total_stay_seconds=round(total, 6),
            interval_count=len(intervals),
        ))

    details.sort(key=lambda item: (item.enter, item.region_id))
    return details, summaries

