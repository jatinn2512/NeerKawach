"""P9 tests use isolated product fixtures and never call live data services."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import integration
from app.main import create_app
from app.services import products


TIMESTAMP = "2026-09-19T00:00:00Z"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    p7 = tmp_path / "inundation"
    (p7 / "metrics").mkdir(parents=True)
    (p7 / "vectors").mkdir()
    (p7 / "roads").mkdir()
    summary = {"source_phase": "P6", "generated_at_utc": TIMESTAMP, "timestamps": [TIMESTAMP], "maximum_flood_depth": {"value_m": 0.2, "timestamp": TIMESTAMP}, "outputs": {}}
    (p7 / "metrics" / "p7_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (p7 / "vectors" / "extent_0000.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [], "properties": {"timestamp": TIMESTAMP}}), encoding="utf-8")
    (p7 / "vectors" / "max_extent.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [], "properties": {"timestamp": "maximum_over_time"}}), encoding="utf-8")
    with (p7 / "metrics" / "inundation_timeseries.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["timestamp", "maximum_flood_depth_m", "inundated_area_m2"])
        writer.writeheader(); writer.writerow({"timestamp": TIMESTAMP, "maximum_flood_depth_m": "0.2", "inundated_area_m2": "10"})
    with (p7 / "roads" / "road_impact_timeseries.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["timestamp", "road_id", "max_intersecting_depth_m", "affected", "risk_class"])
        writer.writeheader(); writer.writerow({"timestamp": TIMESTAMP, "road_id": "way/1", "max_intersecting_depth_m": "0.2", "affected": "True", "risk_class": "moderate"})
    monkeypatch.setattr(products, "P7_ROOT", p7)
    monkeypatch.setattr(products, "P6_ROOT", tmp_path / "coupling")
    monkeypatch.setattr(products, "P8_ROOT", tmp_path / "routing")
    return TestClient(create_app())


def test_health_and_study_area_do_not_leak_paths_or_secrets(client: TestClient) -> None:
    health = client.get("/health")
    area = client.get("/api/study-area")
    assert health.status_code == 200
    assert area.status_code == 200
    text = json.dumps(area.json()).lower()
    assert "earthdata_token" not in text and "c:\\" not in text
    assert area.json()["bbox"]["min_lat"] == 12.925


def test_status_reports_unavailable_p8_without_claiming_a_capability(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(products, "routing_available", lambda: False)
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["api_status"] == "ok"
    assert body["available_data_products"]["p8"] is False
    assert body["routing_capability"] == "unavailable"
    assert "earthdata_token" not in json.dumps(body).lower()


def test_p7_summary_timeseries_extent_and_max_depth(client: TestClient) -> None:
    assert client.get("/api/flood/summary").json()["timestamps"] == [TIMESTAMP]
    assert client.get("/api/flood/timeseries", params={"timestamp": TIMESTAMP}).json()["rows"][0]["maximum_flood_depth_m"] == "0.2"
    assert client.get("/api/flood/extent", params={"timestamp": TIMESTAMP}).json()["properties"]["timestamp"] == TIMESTAMP
    assert client.get("/api/flood/max-depth").json()["maximum_flood_depth"]["value_m"] == 0.2


def test_timestamp_validation_and_unavailable_products(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/flood/timeseries", params={"timestamp": "not-a-time"}).status_code == 422
    assert client.get("/api/flood/extent", params={"timestamp": "2026-09-20T00:00:00Z"}).status_code == 404
    monkeypatch.setattr(products, "P7_ROOT", Path("not-a-real-product-root"))
    response = client.get("/api/flood/summary")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "product_unavailable"


def test_road_impact_and_road_id_validation(client: TestClient) -> None:
    response = client.get("/api/roads/impact", params={"timestamp": TIMESTAMP, "road_id": "way/1"})
    assert response.status_code == 200
    assert response.json()["rows"][0]["affected"] == "True"
    assert client.get("/api/roads/impact", params={"road_id": "../../etc/passwd"}).status_code == 404


def test_routes_validate_request_and_delegate_to_p8(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"origin_latitude": 12.93, "origin_longitude": 77.66, "destination_latitude": 12.94, "destination_longitude": 77.67, "simulation_timestamp": TIMESTAMP, "routing_mode": "baseline"}
    captured: list[str] = []
    def fake_route(*args: object) -> dict:
        captured.append(str(args[-1]))
        return {"status": "ok", "routing_mode": args[-1], "route_timestamp": TIMESTAMP, "total_distance_m": 1.0, "route_cost": 1.0, "maximum_flood_depth_m": 0.0, "affected_segments": [], "avoided_flooded_segments": [], "geometry": {"type": "FeatureCollection", "features": []}, "source_phase": "P8"}
    monkeypatch.setattr(integration, "route_p8", fake_route)
    monkeypatch.setattr(products, "routing_available", lambda: True)
    assert client.post("/api/routes", json=payload).status_code == 200
    payload["routing_mode"] = "flood-aware"
    assert client.post("/api/routes", json=payload).json()["routing_mode"] == "flood-aware"
    assert captured == ["baseline", "flood-aware"]
    payload["origin_latitude"] = 91
    assert client.post("/api/routes", json=payload).status_code == 422
    payload["origin_latitude"] = 12.93; payload["simulation_timestamp"] = "2099-01-01T00:00:00Z"
    assert client.post("/api/routes", json=payload).status_code == 404


def test_route_reports_unavailable_when_locked_p8_inputs_are_absent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(products, "routing_available", lambda: False)
    response = client.post("/api/routes", json={"origin_latitude": 12.93, "origin_longitude": 77.66, "destination_latitude": 12.94, "destination_longitude": 77.67, "simulation_timestamp": TIMESTAMP, "routing_mode": "baseline"})
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "product_unavailable"


def test_rainfall_metadata_and_run_discovery(client: TestClient) -> None:
    rainfall = client.get("/api/rainfall/sources")
    assert rainfall.status_code == 200
    sources = {item["source_id"]: item for item in rainfall.json()["sources"]}
    assert sources["open_meteo_precipitation_forecast"]["source_type"] == "numerical_weather_model_forecast"
    assert sources["rainviewer_radar_observations"]["source_type"] == "radar_observation_timeline"
    assert client.get("/api/runs").json() == {"runs": [{"phase": "P7", "product": "flood inundation and road impact", "timestamps": [TIMESTAMP], "generated_at_utc": TIMESTAMP}]}


def test_rainfall_status_and_nowcast_do_not_claim_unavailable_sources(client: TestClient) -> None:
    status = client.get("/api/rainfall/status")
    assert status.status_code == 200
    body = status.json()
    assert body["source_used"] == "mosdac_insat3dr"
    assert body["source_requested"] == "auto"
    assert body["fallback"] is False
    assert any(item["source_id"] == "mosdac_insat3dr" and item["usable"] is True for item in body["sources"])
    assert any(item["source_id"] == "dwr_qpe" and item["available"] is False for item in body["sources"])
    nowcast = client.get("/api/nowcast/status")
    assert nowcast.status_code == 200
    assert nowcast.json()["future_radar_nowcast"] is False


def test_rainfall_status_reports_explicit_dwr_substitution(client: TestClient) -> None:
    response = client.get("/api/rainfall/status", params={"source_id": "dwr_qpe"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_requested"] == "dwr_qpe"
    assert body["source_used"] == "mosdac_insat3dr"
    assert body["fallback"] is True


def test_current_rainfall_is_labeled_model_forecast(client: TestClient) -> None:
    response = client.get("/api/rainfall/current")
    assert response.status_code == 200
    body = response.json()
    assert body["source_used"] == "open_meteo_precipitation_forecast"
    assert body["source_role"] == "model_forecast"
    assert "Open-Meteo" in body["source_name"]
    assert body["fallback"] is False


def test_historical_mosdac_timeseries_is_real_normalized_product(client: TestClient) -> None:
    response = client.get("/api/rainfall/timeseries", params={"source_id": "mosdac_insat3dr", "start_utc": "2022-08-30T00:00:00Z", "end_utc": "2022-08-30T23:59:59Z"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "mosdac_insat3dr"
    assert body["source_product"] == "3RIMG_L2B_IMC"
    assert body["records"]
    assert all(record["is_observed"] is True and record["is_forecast"] is False for record in body["records"])
    assert all(record["source_product"] == "3RIMG_L2B_IMC" for record in body["records"])
