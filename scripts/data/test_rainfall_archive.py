"""Read-only checks against the local archive. Missing local deliveries skip independently."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.rainfall.providers.mosdac import MosdacProvider
from app.rainfall.registry import load_registry
from app.rainfall_sources import OPEN_METEO_SOURCE
from app.services.rainfall import load_series

DATA = ROOT / "data/rainfall"
AS_OF = datetime(2026, 11, 21, tzinfo=timezone.utc)


def series(source):
    return load_series(source, load_registry()["sources"][source], AS_OF)[0]


def test_small_mosdac_frame_retains_valid_zero_and_native_nodata():
    bbox = dict(min_lon=76, max_lon=78, min_lat=12, max_lat=13)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=2, height=1, count=1, dtype="float32",
                         crs="EPSG:4326", transform=Affine(1, 0, 76, 0, -1, 13), nodata=-999) as ds:
            ds.write(np.array([[0, -999]], dtype="float32"), 1)
            zero, missing = MosdacProvider.frame(ds, Path("3RIMG_01SEP2022_0015_L2B_IMC_V01_IMC.tif"), bbox, 4000)
    assert zero.original_value == zero.derived_value == 0 and not zero.missing
    assert missing.missing and missing.rainfall_mm is None and missing.quality_flags == ("nodata",)
    assert missing.geometry["footprint"] == (77, 12, 78, 13) and missing.geometry["nodata"] == -999
    assert zero.interval_seconds is zero.interval_start_utc is zero.interval_end_utc is None


def test_local_mosdac_csv_matches_every_raw_pixel_time():
    files = sorted((DATA / "raw/mosdac").rglob("*.tif"))
    if not files:
        pytest.skip("raw MOSDAC delivery absent")
    assert len(files) == 341
    parsed = series("mosdac_insat3dr")
    records = {r.source_record_id: r for r in parsed.records}
    assert len(records) == len(parsed.records) == 682
    assert len({r.timestamp_utc for r in records.values()}) == 341
    assert len(set(parsed.missing_labels)) == 91
    bbox = json.loads((ROOT / "config/study_area.json").read_text())["bbox"]
    matched = set()
    for path in files:
        with rasterio.open(path) as ds:
            for raw in MosdacProvider.frame(ds, path, bbox, 4000):
                csv_record = records[raw.source_record_id]
                row, col = raw.geometry["row"], raw.geometry["column"]
                expected = float(ds.read(1)[row, col])
                assert raw.original_value == csv_record.original_value == expected
                assert raw.derived_value == csv_record.derived_value == csv_record.rainfall_mm == expected * 0.5
                assert csv_record.geometry["center"] == pytest.approx(ds.xy(row, col), abs=1e-12, rel=0)
                assert csv_record.geometry["transform_gdal"] == pytest.approx(ds.transform.to_gdal(), abs=1e-12, rel=0)
                assert csv_record.geometry["crs"] == "EPSG:4326" and csv_record.native_resolution_m == 4000
                assert raw.source_file == csv_record.source_file and raw.source_label == csv_record.source_label
                assert csv_record.original_unit == "mm/h" and csv_record.derived_unit == "mm"
                assert csv_record.interval_start_utc is csv_record.interval_end_utc is None
                assert raw.source_record_id not in matched
                matched.add(raw.source_record_id)
    assert matched == set(records)


@pytest.mark.skipif(not (DATA / "raw/imd/17092026.grd").is_file(), reason="IMD grid absent")
def test_local_imd():
    record, = series("imd_ncmrwf_gpm_merged_daily").records
    assert record.original_value == pytest.approx(6.178939, abs=0.000001)
    assert record.reported_date == "2026-09-17"
    assert record.geometry["center"] == (77.75, 13.0) and record.interval_end_utc is None


@pytest.mark.skipif(not list((DATA / "imd").glob("*.csv")), reason="station statement absent")
def test_local_gauge():
    gauge = series("arg_aws")
    assert len(gauge.records) == 31 and len(gauge.missing_labels) == 57
    assert {r.station_id for r in gauge.records} == {"303127776"}
    assert {r.geometry["center"] for r in gauge.records} == {(77.6667, 12.8333)}
    assert gauge.records[0].reported_date == "2022-08-04" and gauge.records[-1].reported_date == "2022-10-30"
    assert all(r.timestamp_utc is None for r in gauge.records)
    assert sum(r.original_value for r in gauge.records) == pytest.approx(616.5)


@pytest.mark.skipif(not list((DATA / "raw/open_meteo").glob("*.json")), reason="forecast captures absent")
def test_local_open_meteo():
    archive = series(OPEN_METEO_SOURCE)
    assert len(archive.captures) == 3 and sum(bool(c["processed_file"]) for c in archive.captures) == 2
    assert len({c["series_id"] for c in archive.captures}) == 1
    assert len({c["retrieved_at_utc"] for c in archive.captures}) == 3
    assert len({r.forecast_valid_utc for r in archive.records}) == len(archive.records) == 72
    assert sum(r.original_value for r in archive.records) == pytest.approx(29.4)
    assert all(r.model_issue_utc is None and r.freshness == "expired" for r in archive.records)


def test_local_imerg():
    assert series("imerg").records == []
