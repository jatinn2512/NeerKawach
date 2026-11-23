"""Time-series coverage at the P9 HTTP boundary, with a fixed source and clock."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.rainfall.contracts import RainfallRecord, RainfallSeries
from app.services import rainfall


@pytest.fixture
def query(monkeypatch):
    source = "mosdac_insat3dr"
    clock = datetime(2026, 11, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(rainfall, "utc_now", lambda: clock)
    def statuses(now):
        assert now == clock
        return [{"source_id": source, "usable": True, "status": "available"}]
    monkeypatch.setattr(rainfall, "source_status", statuses)
    records = [RainfallRecord(f"2022-09-01T{hour}:00Z", 13., 77., depth, source, observed=True)
               for hour, depth in (("16:45", 0.), ("22:15", 3.), ("22:45", 1.))]
    gaps = [f"2022-09-01T{h:02}:{m}:00Z" for h in range(17, 22) for m in ("15", "45")]
    monkeypatch.setattr(rainfall, "load_series", lambda *args, **kw: (RainfallSeries(records, gaps), [Path("raw.csv")]))
    client = TestClient(create_app())
    def get(start, end):
        return client.get("/api/rainfall/timeseries", params={"source_id": source,
                          "start_utc": f"2022-09-01T{start}:00Z", "end_utc": f"2022-09-01T{end}:00Z"})
    return get


def test_dry_and_partial_requests(query):
    dry = query("16:45", "16:45")
    assert dry.status_code == 200 and dry.json()["coverage_status"] == "available"
    assert [r["rainfall_mm"] for r in dry.json()["records"]] == [0.]
    mixed = query("16:45", "22:15")
    assert mixed.status_code == 200
    payload = mixed.json()
    assert payload["coverage_status"] == "partial" and len(payload["missing_labels"]) == 10
    assert [r["rainfall_mm"] for r in payload["records"]] == [0., 3.]
    assert payload["coverage"]["intersecting_gaps"][0]["count"] == 10


@pytest.mark.parametrize(("start", "end", "error"), [
    ("18:15", "18:45", "coverage_gap"), ("18:16", "18:20", "coverage_gap"),
    ("16:00", "16:30", "outside_coverage"), ("23:00", "23:15", "outside_coverage"),
    ("22:20", "22:22", "no_observation_labels")])
def test_empty_request_explains_source_coverage(query, start, end, error):
    response = query(start, end)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == error
    if error == "coverage_gap":
        gap, = response.json()["detail"]["coverage"]["intersecting_gaps"]
        assert gap["before_label"].startswith("2022-09-01T16:45")
        assert gap["after_label"].startswith("2022-09-01T22:15")


def test_request_partly_outside_label_range(query):
    result = query("22:45", "23:45").json()
    assert result["coverage_status"] == "partial" and result["coverage"]["extends_outside_coverage"]
