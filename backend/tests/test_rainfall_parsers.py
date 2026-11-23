"""Small offline fixtures for the source contracts and the registered P9 paths."""
from datetime import datetime, timezone
import json
import struct

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.rainfall import resolver
from app.rainfall.contracts import RainfallValidationError, normalize_record, validate_records
from app.rainfall.providers.imd import ImdStationProvider, read_daily_grid
from app.rainfall.providers.imerg import ImergProvider
from app.rainfall.registry import load_registry
from app.rainfall_sources import OPEN_METEO_SOURCE, OpenMeteoClient
from app.services import rainfall


def test_contract_preserves_interval_and_legacy_aliases():
    row = dict(timestamp="2022-09-01T05:30:00+05:30", latitude=12, longitude=77, source="example",
               rainfall_mm=1.5, original_value=1.5, original_unit="mm", measurement_type="interval_accumulation",
               observed=True, interval_seconds=600, interval_start_utc="2022-09-01T00:00Z",
               interval_end_utc="2022-09-01T00:10Z", quality_flag="checked")
    record = normalize_record(row)
    encoded = record.as_dict()
    assert encoded["timestamp"] == encoded["timestamp_utc"] == "2022-09-01T00:00:00Z"
    assert encoded["is_observed"] is True and encoded["is_forecast"] is False
    assert normalize_record(encoded).as_dict() == encoded
    with pytest.raises(RainfallValidationError, match="original unit"):
        normalize_record({**row, "original_unit": "mm/h"})
    with pytest.raises(RainfallValidationError, match="different rainfall source"):
        normalize_record(row, source="another")
    with pytest.raises(RainfallValidationError, match="duplicate"):
        validate_records([record, record])
    with pytest.raises(RainfallValidationError, match="interval bounds"):
        normalize_record({**row, "interval_seconds": 300})


STATION = """STATION : ELECTRONIC CITY (ARG)
LATITUDE : ,,12.8333 DEG. N
LONGITUDE : ,,77.6667 DEG. E

SL.#,STATION ID, DATE, RAINFALL (MM)
1,303127776,04-08-2022,0
2,303127776,06-08-2022,INVALID
0 indicates that rainfall recorded is 0.0 mm.
"""


def test_station_keeps_zero_invalid_and_unlisted_dates_distinct(tmp_path):
    path = tmp_path / "daily.csv"
    path.write_text(STATION)
    series = ImdStationProvider(tmp_path).read_statement(path)
    dry, invalid = series.records
    assert dry.station_id == "303127776" and dry.geometry["center"] == (77.6667, 12.8333)
    assert dry.geometry["station_name"] == "ELECTRONIC CITY (ARG)" and dry.geometry["crs"] is None
    assert dry.source_label == "04-08-2022" and dry.reported_date == "2022-08-04"
    assert dry.timestamp_utc is dry.interval_start_utc is dry.interval_end_utc is None
    assert dry.original_value == 0 and dry.original_unit == "mm" and not dry.missing
    assert invalid.original_value is invalid.rainfall_mm is None and invalid.missing
    assert invalid.quality_flags == ("invalid_source_value",) and invalid.provenance["source_text"] == "INVALID"
    assert series.missing_labels == ["2022-08-05"]
    assert normalize_record(invalid.as_dict()).as_dict() == invalid.as_dict()


@pytest.mark.parametrize(("old", "new"), [("DEG. N", "DEG. ?"), ("RAINFALL (MM)", "RAINFALL (CM)"),
                                          ("06-08-2022", "04-08-2022"), ("2,303127776", "2,")])
def test_station_rejects_malformed_metadata_header_and_keys(tmp_path, old, new):
    path = tmp_path / "station.csv"
    path.write_text(STATION.replace(old, new))
    with pytest.raises(ValueError):
        ImdStationProvider(tmp_path).read_statement(path)


def test_imd_reads_control_byte_order_and_mask(tmp_path):
    raw = tmp_path / "17092026.grd"
    raw.write_bytes(struct.pack(">2f", 6.178939, -999))
    ctl = tmp_path / "template.ctl"
    ctl.write_text("UNDEF -999\nXDEF 2 LINEAR 77.75 0.25\nYDEF 1 LINEAR 13 0.25\n"
                   "ZDEF 1 LINEAR 1 1\nTDEF 1 LINEAR 1jun2014 1DY\nVARS 1\nrf 0 99 GRIDDED RAINFALL\nENDVARS")
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps(dict(product_date="2026-09-17", byte_order_detected="big-endian",
                                       crs="EPSG:4326", acquired_at_utc="2026-09-18T10:00Z")))
    bbox = dict(min_lon=77.64, max_lon=78.06, min_lat=12.92, max_lat=12.95)
    observed, missing = read_daily_grid(raw, ctl, metadata, bbox).records
    assert observed.original_value == pytest.approx(6.178939)
    assert observed.measurement_type == "daily_accumulation" and observed.original_unit == "mm"
    assert observed.geometry["footprint"] == (77.625, 12.875, 77.875, 13.125)
    assert observed.geometry["transform_gdal"] == (77.625, 0.25, 0.0, 12.875, 0.0, 0.25)
    assert observed.reported_date == "2026-09-17" and observed.retrieved_at_utc.startswith("2026-09-18")
    assert observed.interval_start_utc is observed.interval_end_utc is None
    assert missing.missing and missing.original_value is None and missing.quality_flags == ("nodata",)
    raw.write_bytes(b"x")
    with pytest.raises(RainfallValidationError, match="grid size"):
        read_daily_grid(raw, ctl, metadata, bbox)


def make_capture(directory, stamp, amounts=(0.0, 1.5), issue=None):
    path = directory / f"open_meteo_{stamp}.json"
    path.write_text(json.dumps({"latitude": 12.9, "longitude": 77.65,
        "hourly_units": {"precipitation": "mm"}, "utc_offset_seconds": 0,
        "hourly": {"time": ["2026-09-19T00:00", "2026-09-19T01:00"], "precipitation": amounts}}))
    if issue:
        (directory.parent / "metadata" / path.name).write_text(json.dumps({"model_issue_utc": issue}))
    return path


def test_capture_dedup_and_distinct_revisions(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    first = make_capture(raw, "20260919T000001Z")
    second = make_capture(raw, "20260919T000002Z")
    third = make_capture(raw, "20260919T000003Z", (0.0, 2.0), "2026-09-18T23:00Z")
    archive = OpenMeteoClient.read_archive([third, first, second], [], metadata,
                                           as_of=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert len(archive.records) == 2
    assert [r.original_value for r in archive.records] == [0.0, 2.0]
    assert len({c["series_id"] for c in archive.captures}) == 2
    assert archive.captures[1]["duplicate_of"] == first.stem
    record = archive.records[1]
    assert record.forecast and not record.observed and record.freshness == "expired"
    assert record.forecast_valid_utc == record.timestamp_utc != record.retrieved_at_utc
    assert record.model_issue_utc == "2026-09-18T23:00:00Z"
    assert record.geometry["footprint"] is None and record.interval_seconds == 3600


def test_p9_archive_freshness_discovery_and_exact_source_requests(tmp_path, monkeypatch):
    config = load_registry()["sources"][OPEN_METEO_SOURCE]
    raw = tmp_path / config["raw_directory"]
    raw.mkdir(parents=True)
    processed = tmp_path / config["processed_directory"]
    processed.mkdir(parents=True)
    make_capture(raw, "20260919T000001Z")
    (processed / "imd_gpm_other.csv").write_text("unrelated")
    monkeypatch.setattr(resolver, "ROOT", tmp_path)
    monkeypatch.setattr(rainfall, "ROOT", tmp_path)
    monkeypatch.setattr(rainfall, "DATA_ROOT", tmp_path / "data/rainfall")
    clock = datetime(2026, 9, 19, 0, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(resolver, "utc_now", lambda: clock)
    monkeypatch.setattr(rainfall, "utc_now", lambda: clock)
    client = TestClient(create_app())
    status = client.get("/api/rainfall/current").json()
    assert status["source_used"] == OPEN_METEO_SOURCE and status["source_role"] == "model_forecast"
    selected = next(s for s in status["sources"] if s["source_id"] == OPEN_METEO_SOURCE)
    assert (selected["raw_file_count"], selected["processed_file_count"]) == (1, 0)
    query = {"source_id": OPEN_METEO_SOURCE, "mode": "current"}
    response = client.get("/api/rainfall/timeseries", params=query).json()
    assert len(response["records"]) == 1 and response["records"][0]["is_forecast"]
    assert response["records"][0]["model_issue_utc"] is None
    clock = datetime(2026, 11, 21, tzinfo=timezone.utc)
    assert client.get("/api/rainfall/current").json()["source_used"] is None
    assert client.get("/api/rainfall/timeseries", params=query).status_code == 503
    assert len(client.get("/api/rainfall/timeseries", params={"source_id": OPEN_METEO_SOURCE}).json()["records"]) == 2
    assert client.get("/api/rainfall/status?source_id=imerg").json()["source_used"] is None
    assert client.get("/api/rainfall/timeseries?source_id=imerg").status_code == 503
    provider = ImergProvider(tmp_path / "empty")
    provider.root.mkdir()
    (provider.root / "README.md").write_text("placeholder")
    assert not provider.availability()["available"]


def test_archive_keeps_missing_samples_and_hours(tmp_path):
    raw = make_capture(tmp_path, "20260919T000001Z", (None, 0.0))
    payload = json.loads(raw.read_text())
    payload["hourly"]["time"][1] = "2026-09-19T02:00"
    raw.write_text(json.dumps(payload))
    archive = OpenMeteoClient.read_archive([raw], [], tmp_path / "metadata",
                                           as_of=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert archive.missing_labels == ["2026-09-19T01:00:00Z"]
    missing, dry = archive.records
    assert missing.missing and missing.rainfall_mm is None and missing.original_value is None
    assert not dry.missing and dry.rainfall_mm == 0


def test_imd_csv_only_preserves_rounded_value_basis(tmp_path):
    from app.rainfall.providers.imd import read_daily_csv

    source = "imd_ncmrwf_gpm_merged_daily"
    path = tmp_path / "imd_gpm_2026-09-17.csv"
    path.write_text("timestamp,latitude,longitude,rainfall_mm,source\n"
                    f"2026-09-17T00:00:00Z,13,77.75,6.179,{source}\n")
    record, = read_daily_csv(path, path.with_suffix(".json")).records
    assert record.original_value == 6.179 and record.geometry["footprint"] is None
    assert record.provenance["value_basis"] == "rounded processed CSV"


def test_mosdac_csv_geometry_missing_pixel_and_depth_check(tmp_path):
    from app.rainfall.providers.mosdac import MosdacProvider

    ts = "2022-09-01T00:15:00Z"
    granule = "3RIMG_01SEP2022_0015_L2B_IMC_V01R00_IMC.tif"
    sidecar = tmp_path / "manifest.json"
    sidecar.write_text(json.dumps({
        "source_raster": {"dimensions": [2, 1], "crs": "EPSG:4326", "nodata": -999, "native_resolution_m": 4000,
                          "raw_extent": {"left": 77, "right": 79, "bottom": 12, "top": 13}},
        "records": [{"file": granule, "timestamp_utc": ts, "valid_pixels": 1, "pixels_intersecting_aoi": 2}],
        "study_area": {"bbox": dict(min_lon=77, max_lon=79, min_lat=12, max_lat=13)},
        "temporal_coverage": {"missing_timestamps": ["2022-09-01T00:45:00Z"]}}))
    path = tmp_path / "pixels.csv"
    csv_text = ("timestamp,latitude,longitude,source_pixel_latitude,source_pixel_longitude,"
                "rainfall_mm,rainfall_rate_mm_per_hr,source\n"
                f"{ts},12.5,77.5,12.5,77.5,1,2,mosdac_insat3dr\n")
    path.write_text(csv_text)
    provider = MosdacProvider(tmp_path)
    parsed = provider.read_subset(path, sidecar)
    valid, missing = parsed.records
    assert parsed.missing_labels == ["2022-09-01T00:45:00Z"]
    assert valid.original_value == 2 and valid.derived_value == 1 and valid.original_unit == "mm/h"
    assert valid.geometry["footprint"] == (77, 12, 78, 13) and valid.source_file == granule
    assert missing.missing and missing.original_value is None and missing.geometry["column"] == 1
    path.write_text(csv_text.replace(",1,2,mosdac", ",2,2,mosdac"))
    with pytest.raises(RainfallValidationError, match="derived depth"):
        provider.read_subset(path, sidecar)
