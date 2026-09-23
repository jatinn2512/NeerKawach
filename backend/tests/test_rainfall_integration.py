from __future__ import annotations

from pathlib import Path

import pytest

from app.rainfall.contracts import RainfallValidationError, normalize_record, validate_records
from app.rainfall.providers.dwr import DwrUnavailableError, DwrUnavailableProvider
from app.rainfall.registry import load_registry
from app.rainfall.resolver import resolve_quantitative_source


def test_registry_has_explicit_roles_and_priority() -> None:
    registry = load_registry()
    assert registry["default_quantitative_priority"] == [
        "dwr_qpe", "mosdac_insat3dr", "arg_aws", "imerg", "open_meteo_precipitation_forecast"
    ]
    assert registry["sources"]["rainviewer_radar_observations"]["quantitative"] is False


def test_normalized_contract_preserves_station_and_forecast_metadata() -> None:
    record = normalize_record({
        "timestamp_utc": "2026-09-19T00:00:00+05:30",
        "latitude": "12.94", "longitude": "77.66", "rainfall_mm": "1.2",
        "source": "arg_aws", "station_id": "station-1", "observed": True,
    })
    assert record.timestamp_utc == "2026-09-18T18:30:00Z"
    assert record.station_id == "station-1"
    assert record.observed is True


def test_normalized_contract_rejects_duplicates_and_bad_values() -> None:
    row = {"timestamp": "2026-09-19T00:00:00Z", "latitude": 12.94, "longitude": 77.66, "rainfall_mm": 1, "source": "x"}
    record = normalize_record(row)
    with pytest.raises(RainfallValidationError, match="duplicate"):
        validate_records([record, record])
    with pytest.raises(RainfallValidationError, match="cannot be negative"):
        normalize_record({**row, "rainfall_mm": -1})


def test_resolver_prefers_validated_mosdac_for_historical_data() -> None:
    result = resolve_quantitative_source()
    assert result["source_used"] == "mosdac_insat3dr"
    assert result["source_requested"] == "auto"
    assert result["fallback"] is False
    assert result["fallback_reason"] is None
    assert "dwr_qpe" in result["priority"]


def test_current_resolver_keeps_historical_mosdac_out_of_forecast_mode() -> None:
    result = resolve_quantitative_source(mode="current")
    assert result["source_used"] == "open_meteo_precipitation_forecast"
    assert result["source_requested"] == "auto"
    assert result["fallback"] is False
    assert "mosdac_insat3dr" not in result["priority"]


def test_explicit_unavailable_dwr_substitutes_mosdac() -> None:
    result = resolve_quantitative_source(requested="dwr_qpe")
    assert result["source_used"] == "mosdac_insat3dr"
    assert result["source_requested"] == "dwr_qpe"
    assert result["fallback"] is True
    assert "dwr_qpe" in result["fallback_reason"]


def test_dwr_is_explicitly_unavailable() -> None:
    provider = DwrUnavailableProvider()
    assert provider.availability()["available"] is False
    with pytest.raises(DwrUnavailableError, match="not fabricated"):
        provider.fetch()
