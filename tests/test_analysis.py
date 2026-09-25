from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SQUARE = {"id": "sq", "outer": [[0, 0], [10, 0], [10, 10], [0, 10]]}
T = "2026-01-01T08:00:00+08:00"


def tp(x, y, seconds):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    moment = base + timedelta(seconds=seconds)
    return {"x": x, "y": y, "time": moment.isoformat()}


def analyze(regions, track):
    response = client.post("/api/v1/analyze", json={"regions": regions, "track": track})
    return response


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_straight_crossing_interpolated_times():
    response = analyze([SQUARE], [tp(-10, 5, 0), tp(20, 5, 30)])
    assert response.status_code == 200
    body = response.json()
    assert len(body["details"]) == 1
    interval = body["details"][0]
    assert interval["enter"] == "2026-01-01T08:00:10.000000+08:00"
    assert interval["leave"] == "2026-01-01T08:00:20.000000+08:00"
    assert interval["stay_seconds"] == 10.0
    assert interval["start_truncated"] is False
    assert interval["end_truncated"] is False
    assert body["region_summaries"] == [
        {"region_id": "sq", "total_stay_seconds": 10.0, "interval_count": 1}
    ]


def test_crossing_between_samples_both_outside():
    track = [tp(-5, 5, 0), tp(5, 5, 10), tp(15, 5, 20)]
    body = analyze([SQUARE], track).json()
    assert len(body["details"]) == 1
    interval = body["details"][0]
    assert interval["enter"].endswith("08:00:05.000000+08:00")
    assert interval["leave"].endswith("08:00:15.000000+08:00")
    assert interval["stay_seconds"] == 10.0


def test_hole_excluded_splits_interval():
    region = {
        "id": "holed",
        "outer": [[0, 0], [30, 0], [30, 10], [0, 10]],
        "holes": [[[10, 2], [20, 2], [20, 8], [10, 8]]],
    }
    body = analyze([region], [tp(5, 5, 0), tp(35, 5, 30)]).json()
    details = body["details"]
    assert len(details) == 2
    assert details[0]["enter"].endswith("08:00:00.000000+08:00")
    assert details[0]["leave"].endswith("08:00:05.000000+08:00")
    assert details[0]["start_truncated"] is True
    assert details[1]["enter"].endswith("08:00:15.000000+08:00")
    assert details[1]["leave"].endswith("08:00:25.000000+08:00")
    assert details[1]["end_truncated"] is False
    assert body["region_summaries"][0]["total_stay_seconds"] == 15.0


def test_stationary_inside_counts():
    body = analyze([SQUARE], [tp(5, 5, 0), tp(5, 5, 10)]).json()
    assert len(body["details"]) == 1
    interval = body["details"][0]
    assert interval["stay_seconds"] == 10.0
    assert interval["start_truncated"] is True
    assert interval["end_truncated"] is True


def test_stationary_outside_and_on_boundary_not_counted():
    body = analyze([SQUARE], [tp(0, 0, 0), tp(0, 0, 10)]).json()
    assert body["details"] == []
    body = analyze([SQUARE], [tp(-5, -5, 0), tp(-5, -5, 10)]).json()
    assert body["details"] == []


def test_boundary_touch_and_edge_move_not_counted():
    along_edge = analyze([SQUARE], [tp(0, 0, 0), tp(10, 0, 10)]).json()
    assert along_edge["details"] == []
    vertex_touch = analyze([SQUARE], [tp(-5, -5, 0), tp(0, 0, 10), tp(-5, 5, 20)]).json()
    assert vertex_touch["details"] == []


def test_concave_polygon():
    region = {"id": "concave", "outer": [[0, 0], [10, 0], [10, 10], [5, 5], [0, 10]]}
    body = analyze([region], [tp(5, 8, 0), tp(5, 8, 10)]).json()
    assert body["details"] == []
    body = analyze([region], [tp(2, 2, 0), tp(2, 2, 10)]).json()
    assert body["details"][0]["stay_seconds"] == 10.0


def test_truncation_flags():
    body = analyze([SQUARE], [tp(5, 5, 0), tp(15, 5, 10)]).json()
    interval = body["details"][0]
    assert interval["start_truncated"] is True
    assert interval["end_truncated"] is False
    assert interval["stay_seconds"] == 5.0


def test_overlapping_regions_and_sorting():
    regions = [
        {"id": "b", "outer": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        {"id": "a", "outer": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        {"id": "far", "outer": [[100, 100], [110, 100], [110, 110], [100, 110]]},
    ]
    body = analyze(regions, [tp(-10, 5, 0), tp(20, 5, 30)]).json()
    assert [d["region_id"] for d in body["details"]] == ["a", "b"]
    summaries = {s["region_id"]: s for s in body["region_summaries"]}
    assert summaries["a"]["total_stay_seconds"] == 10.0
    assert summaries["b"]["total_stay_seconds"] == 10.0
    assert summaries["far"]["total_stay_seconds"] == 0.0
    assert summaries["far"]["interval_count"] == 0


def test_duplicate_region_id_rejected():
    response = analyze([SQUARE, SQUARE], [tp(0, 0, 0), tp(1, 1, 1)])
    assert response.status_code == 422
    assert "sq" in response.json()["detail"]


def test_self_intersecting_outer_rejected():
    bowtie = {"id": "bow", "outer": [[0, 0], [10, 10], [10, 0], [0, 10]]}
    response = analyze([bowtie], [tp(0, 0, 0), tp(1, 1, 1)])
    assert response.status_code == 422
    assert "bow" in response.json()["detail"]


def test_hole_outside_outer_rejected():
    region = {
        "id": "bad-hole",
        "outer": [[0, 0], [10, 0], [10, 10], [0, 10]],
        "holes": [[[20, 20], [30, 20], [30, 30], [20, 30]]],
    }
    response = analyze([region], [tp(0, 0, 0), tp(1, 1, 1)])
    assert response.status_code == 422
    assert "bad-hole" in response.json()["detail"]


def test_non_finite_coordinate_rejected():
    response = client.post(
        "/api/v1/analyze",
        content=(
            '{"regions":[{"id":"r","outer":[[0,0],[1,0],[1,1]]}],'
            '"track":[{"x":NaN,"y":0,"time":"2026-01-01T08:00:00+08:00"},'
            '{"x":1,"y":1,"time":"2026-01-01T08:00:01+08:00"}]}'
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_non_increasing_time_rejected():
    response = analyze([SQUARE], [tp(0, 0, 10), tp(1, 1, 10)])
    assert response.status_code == 422
    assert "track point 1" in response.json()["detail"]


def test_naive_time_rejected():
    response = client.post(
        "/api/v1/analyze",
        json={
            "regions": [SQUARE],
            "track": [
                {"x": 0, "y": 0, "time": "2026-01-01T08:00:00"},
                {"x": 1, "y": 1, "time": "2026-01-01T08:00:01+08:00"},
            ],
        },
    )
    assert response.status_code == 422


def test_no_crossing_returns_empty_details():
    body = analyze([SQUARE], [tp(-5, -5, 0), tp(-1, -1, 10)]).json()
    assert body["details"] == []
    assert body["region_summaries"][0]["interval_count"] == 0
