"""Analytical allocation tests and independent read-back of native and event products."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta
import math

import numpy as np
import pytest
import rasterio

from process_temporal_rainfall import RAINFALL, ROOT, grid_allocation, publish, read
from app.rainfall import temporal as t
from app.rainfall.contracts import RainfallRecord
from run_manifest import checksum


def pixel(label="2022-08-31T23:45:00Z", row=1, rate=12.):
    depth = None if rate is None else rate*.5
    return RainfallRecord(label, 13., 77., depth, t.SOURCE, observed=True, missing=rate is None,
                          measurement_type="rainfall_rate", original_unit="mm/h", original_value=rate,
                          derived_value=depth, derived_unit="mm", derivation="rate x 0.5 h",
                          cadence_seconds=1800, geometry={"kind": "grid_cell", "row": row, "column": 18})


def test_unrounded_six_steps_and_native_rate():
    allocated = t.native_allocation(pixel())
    assert [allocated["allocated_step_mm"]]*6 == [1.]*6
    assert allocated["depth_residual_mm"] == 0
    with pytest.raises(ValueError, match="disagrees"):
        t.native_allocation(replace(pixel(), derived_value=72.))


def test_partial_uncovered_and_dry_remain_distinct():
    depth = np.array([[6., 0., np.nan, np.nan]])
    area = np.array([[25., 10., 0., np.nan]])
    terrain = np.array([[True, True, True, False]])
    steps, stats = grid_allocation(depth, depth*2, area, np.array([[1., 1., 0., np.nan]]), terrain)
    np.testing.assert_array_equal(steps, [[1., 0., np.nan, np.nan]])
    assert stats["covered_cells"] == 2
    assert stats["source_volume_m3"] == pytest.approx(.15)
    assert 6*stats["step_volume_m3"] == pytest.approx(.15)
    with pytest.raises(ValueError, match="coverage"):
        grid_allocation(np.nan_to_num(depth), depth*2, area, area>0, terrain)


def test_duplicate_missing_pixels_and_irregular_clock():
    p = pixel()
    with pytest.raises(ValueError, match="duplicate"):
        t.group_pixels([p, p])
    second = replace(p, timestamp_utc="2022-09-01T00:15:00Z")
    frames = t.group_pixels([second, p])
    assert list(frames) == [p.timestamp_utc, second.timestamp_utc]
    steps = list(t.relative_steps(list(frames)))
    assert len(steps) == 12 and steps[6]["relative_start_seconds"] == 1800
    assert steps[6]["timestamp_utc"] == "2022-09-01T00:15:00Z"
    for extra in (pixel("2022-09-01T00:10:00Z"), pixel("2022-09-01T00:45:00Z")):
        frame = t.group_pixels([p, extra])
        with pytest.raises(ValueError):
            t.event_labels(frame, p.timestamp_utc, second.timestamp_utc, {(1,18)})
        with pytest.raises(ValueError):
            list(t.relative_steps(list(frame)))
    missing = pixel(rate=None)
    assert t.native_allocation(missing)["allocated_step_mm"] is None
    with pytest.raises(ValueError, match="missing source pixels"):
        t.event_labels(t.group_pixels([missing]), p.timestamp_utc, p.timestamp_utc, {(1,18)})
    with pytest.raises(ValueError, match="missing source pixels"):
        t.event_labels(frames, p.timestamp_utc, second.timestamp_utc, {(1,18), (2,18)})


def test_leading_trailing_and_off_grid_labels_reported():
    first, last = "2022-12-31T23:15:00Z", "2023-01-01T00:15:00Z"
    frames = t.group_pixels([pixel("2022-12-31T23:45:00Z"), pixel("2022-12-31T23:49:00Z")])
    inventory = t.inventory(frames, first, last)
    assert inventory["off_grid_labels"] == ["2022-12-31T23:49:00Z"]
    a, b = inventory["missing_runs"]
    assert a["before_label_utc"] is None and b["after_label_utc"] is None
    assert [a["labels"], b["labels"]] == [[first], [last]]
    assert inventory["non_nominal_separations"][0]["elapsed_seconds"] == 240


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    if not all((RAINFALL/"mapped"/s/"latest.json").is_file() for s in (t.SOURCE, "imd_ncmrwf_gpm_merged_daily")):
        pytest.skip("local Task 2.3 snapshots unavailable")
    root = tmp_path_factory.mktemp("temporal")
    path = publish(root)
    index = read(root/"latest.json")
    assert root/index["manifest"] == path/"manifest.json"
    assert checksum(path/"manifest.json") == index["manifest_sha256"]
    manifest = read(path/"manifest.json")
    for name, digest in manifest["input_sha256"].items():
        assert checksum(ROOT/name) == digest
    for name, digest in manifest["output_sha256"].items():
        assert checksum(path/name) == digest
    return path


def test_archive_missingness_and_all_native_conservation(bundle):
    root = bundle/t.SOURCE
    info = read(root/"inventory.json")
    frames = read(root/"conservation.json")["frames"]
    gaps = {label for r in info["missing_runs"] for label in r["labels"]}
    assert info["nominal_count"] == 432 and len(frames) == info["present_count"] == 341
    times = [datetime.fromisoformat("2022-08-30T00:15:00Z") + timedelta(minutes=i*30) for i in range(432)]
    assert gaps == {d.isoformat().replace("+00:00","Z") for d in times} - frames.keys()
    assert len(gaps) == 91 and info["longest_missing_run"] == 10
    assert max(r["surrounding_elapsed_seconds"] for r in info["missing_runs"]) == 5.5*3600
    assert not info["off_grid_labels"] and len(info["continuous_nominal_windows"]) == 12
    assert sum(row["count"] for row in info["continuous_nominal_windows"]) == 341
    for r in info["missing_runs"]:
        assert r["before_label_utc"] in frames and r["after_label_utc"] in frames
        assert r["surrounding_elapsed_seconds"] == (1+r["count"])*1800
        assert r["status"] == "missing"
    for f in frames.values():
        with rasterio.open(ROOT/f["native_file"]) as ds:
            raw = ds.read(1)
        assert len(f["native_pixels"]) == 2
        for p in f["native_pixels"]:
            rate = float(raw[p["row"],p["column"]])
            assert p["native_rate_mm_h"] == rate
            assert p["allocated_step_mm"] == pytest.approx(rate/12, abs=1e-12, rel=0)
            assert math.fsum([p["allocated_step_mm"]]*6) == pytest.approx(rate*.5, abs=1e-12, rel=0)
        assert f["grid"]["volume_residual_m3"] < 1e-7
        assert f["grid"]["max_cell_depth_residual_mm"] < 1e-12
    spatial_path = ROOT/read(root/"conservation.json")["mapped_manifest"]
    spatial = read(spatial_path)
    with ExitStack() as stack:
        rasters = {name: stack.enter_context(rasterio.open(spatial_path.parent/name))
                   for name in spatial["output_sha256"]}
        for original in spatial["frames"]:
            saved = frames[original["timestamp_utc"]]
            depth = original["measurements"]["derived_depth"]
            areas = rasters[depth["coverage"]].read(1)
            covered = areas > 0
            values = rasters[depth["raster"]].read(original["band"])[covered]
            # Independent temporal integral from mapped rate and actual covered area.
            rate = rasters[original["measurements"]["rate"]["raster"]].read(original["band"])[covered]
            per_step = np.dot(rate/12, areas[covered])/1000
            allocated = math.fsum([per_step]*6)
            np.testing.assert_allclose(values, (rate/12)*6, atol=1e-12, rtol=0)
            assert allocated == pytest.approx(depth["source_integral"], abs=1e-7, rel=0)
            assert allocated == pytest.approx(saved["grid"]["allocated_volume_m3"], abs=1e-7, rel=0)


@pytest.mark.parametrize(("day", "first_label", "last_label", "wet"), [
    ("2022-09-01", "2022-08-31T22:15:00Z", "2022-09-01T16:45:00Z", 13),
    ("2022-08-31", "2022-08-30T22:15:00Z", "2022-08-31T16:45:00Z", 11)])
def test_all_event_bands(bundle, day, first_label, last_label, wet):
    folder = bundle/t.SOURCE/("bellandur_"+day)
    event = read(folder/"manifest.json")
    steps = read(folder/event["step_index"])
    assert (event["source_observations"], event["generated_steps"], event["relative_end_seconds"]) == (38,228,68400)
    assert len(steps) == 228 and event["wet_observations"] == wet and event["source_completeness"] == "complete"
    assert event["first_label_utc"] == first_label and event["last_label_utc"] == last_label
    assert event["interval_start_utc"] is event["interval_end_utc"] is None
    assert not event["missing_labels"] and event["absolute_interval_status"] == "unknown"
    gaps = {lab for run in read(folder/event["missing_inventory"])["missing_runs"] for lab in run["labels"]}
    spatial = read(ROOT/event["mapped_manifest"])
    mapped_frames = {f["timestamp_utc"]:f for f in spatial["frames"]}
    with ExitStack() as stack:
        def opened(path):
            return stack.enter_context(rasterio.open(path))
        series = opened(folder/event["depth_raster"])
        depth, rate = (opened(ROOT/event[k]) for k in ("mapped_half_hour_depth_mm","mapped_native_rate_mm_h"))
        dem = opened(ROOT/event["dem_valid_raster"]).read(1) == 1
        assert (series.shape,series.crs,series.transform) == (depth.shape,depth.crs,depth.transform)
        assert series.count == 228 and series.dtypes == ("float64",)*228
        assert series.units == ("mm",)*228 and np.isnan(series.nodata) and (~dem).sum() == 301
        assert series.tags()["measurement_type"] == "allocated_depth"
        volume = 0.
        for i, f in enumerate(event["intervals"]):
            label = (datetime.fromisoformat(first_label)+timedelta(minutes=30*i)).isoformat().replace("+00:00","Z")
            assert label == f["timestamp_utc"] and label not in gaps
            assert f["source_interval_index"] == i and len(f["native_pixels"]) == 2
            assert all(p["status"] in ("wet","dry") for p in f["native_pixels"])
            original = mapped_frames[label]
            assert f["native_file"] == original["source_file"] and f["source_label"] == original["source_label"]
            assert f["mapped_band"] == original["band"]
            parent = depth.read(f["mapped_band"])
            native_rate = rate.read(f["mapped_band"])
            with rasterio.open(ROOT/f["coverage_raster"]) as cov:
                area, fraction, valid = cov.read()
            supported = (valid == 1) & dem
            assert supported.sum() == 8914 and np.allclose(fraction[dem],1)
            total = np.zeros_like(parent)
            for part in range(6):
                j = 6*i+part
                step = steps[j]
                assert step["timestamp_utc"] == label and step["source_label"] == original["source_label"]
                assert step["coverage_raster"] == f["coverage_raster"] and step["source_interval_index"] == i
                assert step["assumption"] == event["assumption"] and step["absolute_interval_status"] == "unknown"
                assert (step["band"],step["relative_start_seconds"],step["relative_end_seconds"]) == (j+1,300*j,300*(j+1))
                values = series.read(j+1)
                np.testing.assert_array_equal(np.isfinite(values), supported)
                np.testing.assert_allclose(values[supported], native_rate[supported]/12, rtol=0, atol=1e-12)
                total += values
            np.testing.assert_allclose(total[supported], parent[supported], rtol=0, atol=1e-12)
            actual_vol = float(np.sum(total[supported]*area[supported])/1000)
            expected = original["measurements"]["derived_depth"]["source_integral"]
            assert actual_vol == pytest.approx(expected, abs=1e-7, rel=0)
            volume += actual_vol
        assert volume == pytest.approx(event["source_volume_m3"], abs=1e-7, rel=0)
    assert len(list((bundle/t.SOURCE).glob("*/allocated_depth_mm.tif"))) == 2


def test_source_native_clocks(bundle):
    imd, gauge, forecast, imerg = [read(bundle/name/"native.json") for name in
                                  ("imd_ncmrwf_gpm_merged_daily","arg_aws","open_meteo_precipitation_forecast","imerg")]
    assert all(s["allocated_steps"] == 0 for s in (imd,gauge,forecast,imerg))
    record, = imd["records"]
    assert record["interval_start_utc"] is record["interval_end_utc"] is None
    assert record["interval_seconds"] == 86400 and record["measurement_type"] == "daily_accumulation"
    assert len(gauge["records"]) == 31 and len(gauge["missing_labels"]) == 57
    assert not {r["reported_date"] for r in gauge["records"]}.intersection(gauge["missing_labels"])
    assert all(r["interval_seconds"] == 86400 and r["timestamp_utc"] is None for r in gauge["records"])
    assert len({r["forecast_valid_utc"] for r in forecast["records"]}) == len(forecast["records"]) == 72
    assert all(r["forecast"] and r["interval_seconds"] == 3600 and r["retrieved_at_utc"] for r in forecast["records"])
    assert imerg["status"] == "unavailable" and not imerg["records"]
