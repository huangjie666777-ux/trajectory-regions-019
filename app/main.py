"""HTTP API for the trajectory region-crossing analysis service."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .analysis import (
    AnalysisError,
    TrajectoryPoint,
    analyze_region,
    build_region_polygon,
    validate_trajectory,
)

app = FastAPI(
    title="Trajectory Region Analysis",
    version="1.0.0",
    description=(
        "Analyzes when a trajectory (piecewise-linear, constant speed between "
        "samples) dwells inside polygonal regions. Planar metric coordinates; "
        "region boundaries count as outside."
    ),
)

TIME_PRECISION = "microsecond"  # ISO8601 output and dwell seconds precision


class RegionIn(BaseModel):
    id: str = Field(min_length=1)
    outer: list[list[float]] = Field(
        description="Outer ring as [[x, y], ...]; first/last may repeat."
    )
    holes: list[list[list[float]]] = Field(default_factory=list)


class TrajectoryPointIn(BaseModel):
    x: float
    y: float
    time: datetime = Field(description="ISO8601 timestamp with timezone offset")


class AnalyzeRequest(BaseModel):
    regions: list[RegionIn] = Field(min_length=1)
    trajectory: list[TrajectoryPointIn] = Field(min_length=2)


class IntervalOut(BaseModel):
    region_id: str
    enter: str
    exit: str
    dwell_seconds: float
    truncated_start: bool
    truncated_end: bool


class RegionSummaryOut(BaseModel):
    region_id: str
    total_dwell_seconds: float
    interval_count: int


class AnalyzeResponse(BaseModel):
    time_precision: str
    details: list[IntervalOut]
    regions: list[RegionSummaryOut]


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")


def _round(seconds: float) -> float:
    return round(seconds, 6)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    errors: list[str] = []

    seen: set[str] = set()
    polygons: list[tuple[str, Any]] = []
    for region in req.regions:
        if region.id in seen:
            errors.append(f"region '{region.id}': duplicate region id")
            continue
        seen.add(region.id)
        try:
            polygons.append((region.id, build_region_polygon(region.id, region.outer, region.holes)))
        except AnalysisError as exc:
            errors.append(str(exc))

    points = [TrajectoryPoint(p.x, p.y, p.time) for p in req.trajectory]
    try:
        validate_trajectory(points)
    except AnalysisError as exc:
        errors.append(str(exc))

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    results = [analyze_region(rid, poly, points) for rid, poly in polygons]

    details: list[IntervalOut] = []
    summaries: list[RegionSummaryOut] = []
    for res in results:
        for iv in res.intervals:
            details.append(
                IntervalOut(
                    region_id=res.region_id,
                    enter=_iso(iv.start),
                    exit=_iso(iv.end),
                    dwell_seconds=_round(iv.seconds),
                    truncated_start=iv.truncated_start,
                    truncated_end=iv.truncated_end,
                )
            )
        summaries.append(
            RegionSummaryOut(
                region_id=res.region_id,
                total_dwell_seconds=_round(res.total_seconds),
                interval_count=len(res.intervals),
            )
        )

    details.sort(key=lambda d: (d.enter, d.region_id))
    return AnalyzeResponse(
        time_precision=TIME_PRECISION,
        details=details,
        regions=summaries,
    )
