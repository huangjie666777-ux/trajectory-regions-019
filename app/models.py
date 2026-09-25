from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, FiniteFloat, field_validator


class RegionIn(BaseModel):
    id: str = Field(min_length=1)
    outer: List[List[FiniteFloat]] = Field(min_length=3)
    holes: List[List[List[FiniteFloat]]] = Field(default_factory=list)

    @field_validator("outer")
    @classmethod
    def _check_outer_points(cls, ring):
        for point in ring:
            if len(point) != 2:
                raise ValueError("outer ring points must be [x, y] pairs")
        return ring

    @field_validator("holes")
    @classmethod
    def _check_hole_points(cls, holes):
        for ring in holes:
            if len(ring) < 3:
                raise ValueError("hole rings need at least 3 points")
            for point in ring:
                if len(point) != 2:
                    raise ValueError("hole ring points must be [x, y] pairs")
        return holes


class TrackPointIn(BaseModel):
    x: FiniteFloat
    y: FiniteFloat
    time: datetime

    @field_validator("time")
    @classmethod
    def _require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("track point time must include a timezone offset")
        return value


class AnalyzeRequest(BaseModel):
    regions: List[RegionIn] = Field(min_length=1)
    track: List[TrackPointIn] = Field(min_length=2)


class IntervalOut(BaseModel):
    region_id: str
    enter: str
    leave: str
    stay_seconds: float
    start_truncated: bool = False
    end_truncated: bool = False


class RegionSummaryOut(BaseModel):
    region_id: str
    total_stay_seconds: float
    interval_count: int


class AnalyzeResponse(BaseModel):
    details: List[IntervalOut]
    region_summaries: List[RegionSummaryOut]

