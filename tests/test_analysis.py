from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
T0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def square(rid="R1", lo=0.0, hi=10.0, holes=None):
    return {
        "id": rid,
        "outer": [[lo, lo], [hi, lo], [hi, hi], [lo, hi]],
        "holes": holes or [],
    }


def analyze(regions, trajectory):
    resp = client.post("/api/v1/analyze", json={"regions": regions, "trajectory": trajectory})
    assert resp.status_code == 200, resp.json()
    return resp.json()


def pt(x, y, s):
    return {"x": x, "y": y, "time": ts(s)}


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_simple_crossing_both_endpoints_outside():
    # Cross a 10x10 region horizontally at y=5, speed 1 m/s.
    data = analyze([square()], [pt(-5, 5, 0), pt(15, 5, 20)])
    assert len(data["details"]) == 1
    d = data["details"][0]
    assert d["enter"] == ts(5)
    assert d["exit"] == ts(15)
    assert d["dwell_seconds"] == 10.0
    assert d["truncated_start"] is False and d["truncated_end"] is False
    assert data["regions"][0]["total_dwell_seconds"] == 10.0


def test_diagonal_crossing_time_proportional():
    # Diagonal through square corner-to-corner: enter at (0,0)? boundary is
    # outside, so use a chord crossing interior: (-1,5)->(11,5) is horizontal.
    # Use diagonal from (-5,-5) to (15,15): enters (0,0) t=5, leaves (10,10) t=15.
    data = analyze([square()], [pt(-5, -5, 0), pt(15, 15, 20)])
    d = data["details"][0]
    assert d["enter"] == ts(5) and d["exit"] == ts(15)


def test_hole_excluded():
    hole = [[4, 4], [6, 4], [6, 6], [4, 6]]
    # Cross horizontally through the hole: two separate inside intervals.
    data = analyze([square(holes=[hole])], [pt(-5, 5, 0), pt(15, 5, 20)])
    details = data["details"]
    assert len(details) == 2
    assert details[0]["enter"] == ts(5) and details[0]["exit"] == ts(9)
    assert details[1]["enter"] == ts(11) and details[1]["exit"] == ts(15)
    assert data["regions"][0]["total_dwell_seconds"] == 8.0


def test_stationary_inside_counts():
    # Move into region, stay still 30s, then leave.
    traj = [pt(-5, 5, 0), pt(5, 5, 10), pt(5, 5, 40), pt(15, 5, 50)]
    data = analyze([square()], traj)
    assert len(data["details"]) == 1
    d = data["details"][0]
    assert d["enter"] == ts(5) and d["exit"] == ts(45)
    assert d["dwell_seconds"] == 40.0


def test_truncation_at_start_and_end():
    # Trajectory starts and ends inside the region.
    data = analyze([square()], [pt(5, 5, 0), pt(6, 5, 10)])
    d = data["details"][0]
    assert d["enter"] == ts(0) and d["exit"] == ts(10)
    assert d["truncated_start"] is True and d["truncated_end"] is True
    assert d["dwell_seconds"] == 10.0


def test_vertex_touch_not_counted():
    # Tangent to the corner (10,10): touches a single vertex only.
    data = analyze([square()], [pt(5, 15, 0), pt(15, 5, 20)])
    assert data["details"] == []
    assert data["regions"][0]["total_dwell_seconds"] == 0.0


def test_along_boundary_not_counted():
    # Move exactly along the edge y=0, then away.
    data = analyze([square()], [pt(-5, 0, 0), pt(15, 0, 20), pt(15, -5, 25)])
    assert data["details"] == []


def test_adjacent_intervals_merged():
    # Two segments forming a polyline fully inside after entry: intervals
    # sharing the same timestamp merge into one.
    traj = [pt(-5, 5, 0), pt(5, 5, 10), pt(5, 8, 13), pt(15, 8, 23)]
    data = analyze([square()], traj)
    assert len(data["details"]) == 1
    d = data["details"][0]
    assert d["enter"] == ts(5) and d["exit"] == ts(18)
    assert d["dwell_seconds"] == 13.0


def test_multiple_regions_overlap_and_sorting():
    regions = [square("B", 0, 10), square("A", 5, 15)]
    # Path crosses B then A; overlap zone belongs to both.
    data = analyze(regions, [pt(-5, 7.5, 0), pt(20, 7.5, 25)])
    assert [d["region_id"] for d in data["details"]] == ["B", "A"]
    totals = {r["region_id"]: r["total_dwell_seconds"] for r in data["regions"]}
    assert totals == {"A": 10.0, "B": 10.0}


def test_no_region_hit_returns_empty_details():
    data = analyze([square()], [pt(-20, -20, 0), pt(-10, -10, 10)])
    assert data["details"] == []
    assert data["regions"][0]["interval_count"] == 0


def test_concave_polygon():
    # L-shaped concave region; path passes through the notch (outside) then
    # re-enters.
    region = {
        "id": "L",
        "outer": [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]],
        "holes": [],
    }
    # Horizontal line y=2 from x=-5 to 15: inside 0..10 only (notch is y>=4).
    data = analyze([region], [pt(-5, 2, 0), pt(15, 2, 20)])
    assert len(data["details"]) == 1
    assert data["details"][0]["dwell_seconds"] == 10.0


def test_duplicate_region_id_rejected():
    resp = client.post(
        "/api/v1/analyze",
        json={"regions": [square("X"), square("X")], "trajectory": [pt(0, 0, 0), pt(1, 1, 1)]},
    )
    assert resp.status_code == 422
    assert "duplicate region id" in str(resp.json()["detail"])
    assert "X" in str(resp.json()["detail"])


def test_self_intersecting_region_rejected():
    bowtie = {"id": "BAD", "outer": [[0, 0], [10, 10], [10, 0], [0, 10]], "holes": []}
    resp = client.post(
        "/api/v1/analyze",
        json={"regions": [bowtie], "trajectory": [pt(0, 0, 0), pt(1, 1, 1)]},
    )
    assert resp.status_code == 422
    assert "BAD" in str(resp.json()["detail"])


def test_invalid_hole_rejected():
    hole_outside = [[20, 20], [30, 20], [30, 30], [20, 30]]
    resp = client.post(
        "/api/v1/analyze",
        json={
            "regions": [square("H", holes=[hole_outside])],
            "trajectory": [pt(0, 0, 0), pt(1, 1, 1)],
        },
    )
    assert resp.status_code == 422
    assert "H" in str(resp.json()["detail"])


def test_non_finite_coordinate_rejected():
    body = (
        '{"regions": [%s], "trajectory": [%s, {"x": 1e999, "y": 1, "time": "%s"}]}'
        % (__import__("json").dumps(square()), __import__("json").dumps(pt(0, 0, 0)), ts(1))
    )
    resp = client.post("/api/v1/analyze", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert "trajectory point 1" in str(resp.json()["detail"])


def test_non_increasing_time_rejected():
    resp = client.post(
        "/api/v1/analyze",
        json={"regions": [square()], "trajectory": [pt(0, 0, 5), pt(1, 1, 5)]},
    )
    assert resp.status_code == 422
    assert "strictly increasing" in str(resp.json()["detail"])


def test_naive_timestamp_rejected():
    resp = client.post(
        "/api/v1/analyze",
        json={
            "regions": [square()],
            "trajectory": [
                {"x": 0, "y": 0, "time": "2026-09-24T08:00:00"},
                {"x": 1, "y": 1, "time": "2026-09-24T08:00:01"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "timezone offset" in str(resp.json()["detail"])


def test_requests_are_independent():
    bad = client.post("/api/v1/analyze", json={"regions": [], "trajectory": []})
    assert bad.status_code == 422
    ok = analyze([square()], [pt(-5, 5, 0), pt(15, 5, 20)])
    assert len(ok["details"]) == 1
