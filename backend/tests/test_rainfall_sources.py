from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.rainfall_sources import OpenMeteoClient, RainViewerClient, RainfallSourceError


def response(payload: dict, request: httpx.Request, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=request)


def open_meteo_payload() -> dict:
    return {
        "latitude": 12.94,
        "longitude": 77.66,
        "elevation": 900.0,
        "generationtime_ms": 0.2,
        "utc_offset_seconds": 0,
        "timezone": "UTC",
        "timezone_abbreviation": "GMT",
        "hourly_units": {"time": "iso8601", "precipitation": "mm"},
        "hourly": {"time": ["2026-09-19T00:00Z", "2026-09-19T01:00Z"], "precipitation": [0.4, 1.2]},
    }


def rainviewer_payload(past: list[dict] | None = None) -> dict:
    return {
        "version": "2.0",
        "generated": 1789791622,
        "host": "https://tilecache.rainviewer.com",
        "radar": {"past": past if past is not None else [{"time": 1789791000, "path": "/v2/radar/example"}], "nowcast": []},
    }


def test_configuration_loads_public_sources_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPEN_METEO_API_KEY", raising=False)
    monkeypatch.delenv("RAINVIEWER_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.open_meteo_enabled is True
    assert settings.rainviewer_enabled is True
    assert settings.open_meteo_base_url == "https://api.open-meteo.com"
    assert settings.rainviewer_base_url.endswith("weather-maps.json")


def test_open_meteo_success_and_normalization(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/forecast"
        assert request.url.params["hourly"] == "precipitation"
        assert "apikey" not in request.url.params
        return response(open_meteo_payload(), request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = OpenMeteoClient(base_url="https://example.test", http_client=client, retries=0).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    rows = (tmp_path / "processed" / "open_meteo_20260919T000000Z.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3
    assert metadata["source_type"] == "numerical_weather_model_forecast"
    assert metadata["response_grid_coordinate"] == {"latitude": 12.94, "longitude": 77.66}
    assert Path(tmp_path / "raw" / "open_meteo" / "open_meteo_20260919T000000Z.json").exists()


def test_open_meteo_malformed_response_is_rejected_and_raw_is_preserved(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response({"hourly_units": {"precipitation": "mm"}, "hourly": {"time": ["bad"], "precipitation": []}}, request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RainfallSourceError, match="time/precipitation arrays"):
            OpenMeteoClient(base_url="https://example.test", http_client=client, retries=0).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    assert (tmp_path / "raw" / "open_meteo" / "open_meteo_20260919T000000Z.json").exists()


def test_open_meteo_timeout_retries_then_succeeds(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return response(open_meteo_payload(), request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = OpenMeteoClient(base_url="https://example.test", http_client=client, retries=1, sleep=lambda _: None).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    assert calls == 2
    assert metadata["record_count"] == 2


def test_rainviewer_success_stores_frame_references_without_rainfall_values(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/public/weather-maps.json"
        return response(rainviewer_payload(), request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = RainViewerClient(base_url="https://example.test/public/weather-maps.json", http_client=client, retries=0).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    frame = metadata["past_frames"][0]
    assert metadata["source_type"] == "radar_observation_timeline"
    assert metadata["authentication_required"] is False
    assert metadata["quantitative_rainfall_available"] is False
    assert frame["rainfall_mm"] is None
    assert "12.935000/77.660000" in frame["bellandur_tile_url"]
    assert metadata["attribution"]["required_for_user_facing_visualization"] is True
    assert list((tmp_path / "raw" / "rainviewer").glob("*.json"))


def test_rainviewer_unavailable_past_frames_are_explicit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response(rainviewer_payload(past=[]), request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = RainViewerClient(base_url="https://example.test/public/weather-maps.json", http_client=client, retries=0).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    assert metadata["past_frame_count"] == 0
    assert metadata["future_nowcast_available"] is False
    assert metadata["nowcast_frames_received"] == 0


def test_rainviewer_malformed_frame_fails_clearly(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response(rainviewer_payload(past=[{"time": "not-a-time", "path": "/v2/radar/bad"}]), request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RainfallSourceError, match="malformed radar frame"):
            RainViewerClient(base_url="https://example.test/public/weather-maps.json", http_client=client, retries=0).fetch(output_root=tmp_path, retrieved_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
