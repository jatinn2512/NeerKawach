"""Spatial-only analytic tests and read-back verification of the genuine local products."""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import transform

from map_rainfall import GRID_FILE, OUTPUT_ROOT, ROOT, publish
from app.rainfall.contracts import RainfallRecord
from app.rainfall.providers.mosdac import parse_timestamp
from app.rainfall.spatial import (IMD, INELIGIBLE, MOSDAC, FootprintMap, WorkingGrid, projected_ring)
from run_manifest import checksum


def small_grid(valid):
    return WorkingGrid(CRS.from_epsg(32643), Affine(10, 0, 0, 0, -10, 10), np.array(valid, dtype=bool))


def pixel(bounds, value, col=0, source=MOSDAC):
    is_rate = source == MOSDAC
    depth = value/2 if is_rate and value is not None else value
    return RainfallRecord("2022-09-01T00:15:00Z", 12.9, 77.7, depth, source, product="fixture",
                          measurement_type="rainfall_rate" if is_rate else "daily_accumulation",
                          original_value=value, original_unit="mm/h" if is_rate else "mm",
                          derived_value=depth if is_rate else None, derived_unit="mm" if is_rate else None,
                          derivation="rate x 0.5 h" if is_rate else None, missing=value is None,
                          geometry={"kind": "grid_cell", "row": 0, "column": col, "crs": "EPSG:32643",
                                    "footprint": bounds})


def test_fractional_boundary_and_units():
    grid = small_grid([[1]])
    records = [pixel((0, 0, 2.5, 10), 2), pixel((2.5, 0, 10, 10), 10, 1)]
    weights = FootprintMap(grid, records)
    assert weights.domain_area == {(0, 0): 25.0, (0, 1): 75.0}
    rate = weights.map(records, "rate")
    depth = weights.map(records, "derived_depth")
    assert rate.covered_m2.item() == 100 and rate.coverage_fraction.item() == 1
    assert rate.values.item() == 8 and depth.values.item() == 4
    assert (rate.unit, rate.integral_unit, rate.mapped_integral) == ("mm/h", "m³/h", .8)
    assert (depth.unit, depth.integral_unit, depth.mapped_integral) == ("mm", "m³", .4)


def test_partial_uncovered_and_dem_void():
    grid = small_grid([[1, 1, 0]])
    record = pixel((0, 0, 2.5, 10), 12, source=IMD)
    result = FootprintMap(grid, [record]).map([record], "daily_depth")
    np.testing.assert_array_equal(result.values, [[12, np.nan, np.nan]])
    np.testing.assert_array_equal(result.covered_m2, [[25, 0, 0]])
    np.testing.assert_array_equal(result.coverage_fraction, [[.25, 0, 0]])
    np.testing.assert_array_equal(result.source_valid, [[True, False, False]])
    assert result.source_integral == result.mapped_integral == .3


def test_missing_pixel_and_dry_reading():
    grid = small_grid([[1]])
    a, b = pixel((0, 0, 5, 10), 0), pixel((5, 0, 10, 10), None, 1)
    weights = FootprintMap(grid, [a, b])
    for records in ([a], [a, b]):
        mapped = weights.map(records, "rate")
        assert mapped.coverage_fraction.item() == .5 and mapped.values.item() == 0
        assert mapped.contributors == ((0, 0),)
    missing = weights.map([b], "rate")
    assert np.isnan(missing.values.item()) and missing.covered_m2.item() == 0
    assert missing.mapped_integral == 0 and not missing.source_valid.item()


def test_reject_double_counting_inside_partially_covered_cell():
    grid = small_grid([[1]])
    with pytest.raises(ValueError, match="overlapping native pixels"):
        FootprintMap(grid, [pixel((0, 0, 4, 10), 1), pixel((2, 0, 5, 10), 2, 1)])


def test_valid_domain_with_interior_holes():
    grid = small_grid([[1, 0, 1], [0, 1, 0], [1, 0, 1]])
    rec = pixel((5, -15, 26, 8), 1, source=IMD)
    expected = np.array([[40, 0, 48], [0, 100, 0], [25, 0, 30]])
    weights = FootprintMap(grid, [rec])
    np.testing.assert_allclose(weights.area[(0, 0)], expected)
    assert weights.domain_area[(0, 0)] == pytest.approx(243)


def test_frame_identity_and_measurement_guards():
    grid = small_grid([[1]])
    a = pixel((0, 0, 5, 10), 1)
    weights = FootprintMap(grid, [a])
    with pytest.raises(ValueError, match="one observed timestamp"):
        weights.map([a, replace(a, timestamp_utc="2022-09-02T00:15Z")], "rate")
    with pytest.raises(ValueError, match="one observed timestamp"):
        weights.map([replace(a, timestamp_utc=None, reported_date=day)
                     for day in ("2022-09-01", "2022-09-02")], "rate")
    with pytest.raises(ValueError, match="duplicate"):
        weights.map([a, a], "rate")
    for field in ("daily_depth", "forecast"):
        with pytest.raises(ValueError, match="incompatible"):
            weights.map([a], field)
    with pytest.raises(ValueError, match="mixed source"):
        weights.map([pixel((0, 0, 5, 10), 1, source=IMD)], "rate")


@pytest.mark.parametrize("source", INELIGIBLE)
def test_point_and_unavailable_sources_are_ineligible(source):
    with pytest.raises(ValueError, match=INELIGIBLE[source][:-1]):
        FootprintMap(small_grid([[1]]), [replace(pixel((0, 0, 5, 10), 1), source=source, geometry=None)])


@pytest.fixture(scope="module")
def local_grid():
    if not GRID_FILE.exists():
        pytest.skip("local Phase 1 working grid unavailable")
    dem = ROOT / json.loads(GRID_FILE.read_text())["outputs"]["dem"]["file"]
    return WorkingGrid.read(dem, GRID_FILE), dem


def test_uniform_one_mm_on_actual_valid_domain(local_grid):
    grid, _ = local_grid
    assert grid.valid.shape == (97, 95) and grid.cell_area == 900
    a = grid.affine
    record = pixel((a.c-100, a.f+97*a.e-100, a.c+95*a.a+100, a.f+100), 1, source=IMD)
    mapped = FootprintMap(grid, [record]).map([record], "daily_depth")
    assert grid.valid.sum() == 8914 and (~grid.valid).sum() == 301
    assert mapped.covered_m2.sum() == pytest.approx(8_022_600, abs=1e-7, rel=0)
    assert mapped.mapped_integral == pytest.approx(8022.6, abs=1e-9, rel=0)
    assert mapped.source_integral == pytest.approx(8022.6, abs=1e-9, rel=0)
    assert np.isnan(mapped.values[~grid.valid]).all()


def test_densification_and_registration(local_grid):
    grid, _ = local_grid
    bounds = (77.625, 12.875, 77.875, 13.125)
    ring = projected_ring(bounds, "EPSG:4326", grid)
    assert len(ring) >= 4000
    # Independently project the midpoint of the southern parallel. The chord
    # between its two projected endpoints misses this point noticeably.
    lon, lat = (bounds[0]+bounds[2])/2, bounds[1]
    x, y = transform("EPSG:4326", grid.crs, [lon], [lat])
    a = grid.affine
    expected = np.array([(x[0]-a.c)/a.a, (y[0]-a.f)/a.e])
    np.testing.assert_allclose(ring[500], expected, rtol=0, atol=1e-9)
    chord = (np.array(ring[0])+ring[1000])/2
    assert np.linalg.norm(expected-chord)*abs(a.a) > 0.1
    np.testing.assert_allclose(grid.affine.to_gdal(), (787205.6082538622,30,0,1432892.5695289308,0,-30),
                               rtol=0, atol=1e-7)


def open_local_snapshot(source, grid, dem, temporary):
    pointer = OUTPUT_ROOT/source/"latest.json"
    if pointer.exists():
        latest = json.loads(pointer.read_text())
        path = pointer.parent/latest["manifest"]
        assert checksum(path) == latest["manifest_sha256"]
    else:
        path = publish(source, grid, GRID_FILE, dem, temporary)/"manifest.json"
    manifest = json.loads(path.read_text())
    for name, digest in manifest["input_sha256"].items():
        assert checksum(ROOT/name) == digest
    for name, digest in manifest["output_sha256"].items():
        assert checksum(path.parent/name) == digest
        with rasterio.open(path.parent/name) as ds:
            assert (ds.shape, ds.crs, ds.transform) == (grid.valid.shape, grid.crs, grid.affine)
    with rasterio.open(path.parent/"dem_valid.tif") as ds:
        np.testing.assert_array_equal(ds.read(1), grid.valid)
    return path.parent, manifest


def check_saved_coverage(ds, grid):
    area, fraction, valid = ds.read()
    for layer in (area, fraction, valid):
        np.testing.assert_array_equal(np.isfinite(layer), grid.valid)
    np.testing.assert_allclose(area[grid.valid], 900, atol=1e-8, rtol=0)
    np.testing.assert_allclose(fraction[grid.valid], 1, atol=1e-11, rtol=0)
    assert np.all(valid[grid.valid] == 1)
    return area


def north_area_from_inverse_projection(grid, parallel):
    """Third check: intersect cell quadrilaterals with the observed latitude boundary.

    Interpolate latitude only along each 30 m target edge for this independent check.
    It has a small geometric approximation error separate from summation roundoff.
    """
    rows, cols = np.indices(tuple(s+1 for s in grid.valid.shape))
    a = grid.affine
    _, latitude = transform(grid.crs, "EPSG:4326", (a.c+cols*a.a).ravel(), (a.f+rows*a.e).ravel())
    lat = np.array(latitude).reshape(rows.shape)
    corners = np.stack([lat[:-1,:-1], lat[:-1,1:], lat[1:,1:], lat[1:,:-1]], axis=-1)
    north = corners >= parallel
    areas = np.where(north.all(axis=-1) & grid.valid, grid.cell_area, 0.)
    square = np.array([(0.,0.), (1.,0.), (1.,1.), (0.,1.)])
    for r, c in np.argwhere(north.any(axis=-1) & ~north.all(axis=-1) & grid.valid):
        vertices = []
        for i in range(4):
            j = (i+1)%4
            if north[r,c,i]:
                vertices.append(square[i])
            if north[r,c,i] != north[r,c,j]:
                t = (parallel-corners[r,c,i])/(corners[r,c,j]-corners[r,c,i])
                vertices.append(square[i]+t*(square[j]-square[i]))
        x, y = np.array(vertices).T
        areas[r,c] = abs(np.sum(x*np.roll(y,-1)-y*np.roll(x,-1)))*grid.cell_area/2
    return areas


def test_every_archived_mosdac_band_and_integral(local_grid, tmp_path):
    raw = sorted((ROOT/"data/rainfall/raw/mosdac").rglob("*.tif"))
    if not raw:
        pytest.skip("local MOSDAC TIFFs unavailable")
    grid, dem = local_grid
    folder, manifest = open_local_snapshot(MOSDAC, grid, dem, tmp_path)
    frames = {f["timestamp_utc"]: f for f in manifest["frames"]}
    assert len(raw) == len(frames) == 341
    assert {parse_timestamp(p) for p in raw} == set(frames)
    gaps = set(manifest["missing_utc_labels"])
    assert len(gaps) == 91 and set(frames).isdisjoint(gaps)
    with rasterio.open(raw[0]) as src:
        parallel = src.transform.f + 2*src.transform.e
    independent = north_area_from_inverse_projection(grid, parallel)
    with ExitStack() as stack:
        def opened(name):
            return stack.enter_context(rasterio.open(folder/name))
        rate, depth = opened("rate.tif"), opened("derived_depth.tif")
        assert rate.count == depth.count == 341 and tuple(sorted(frames)) == rate.descriptions == depth.descriptions
        weights = opened("overlap_1.tif").read()
        np.testing.assert_allclose(weights[0,grid.valid], independent[grid.valid], rtol=0, atol=.0005)
        assert ((weights[0] > 0) & (weights[1] > 0)).sum() == 94
        coverage = {name:check_saved_coverage(opened(name), grid) for name in manifest["coverage_products"]}
        for path in raw:
            frame = frames[parse_timestamp(path)]
            band = frame["band"]
            with rasterio.open(path) as src:
                rates = src.read(1)[[1,2],18].astype(float)
                assert frame["records"][0]["geometry"]["transform_gdal"] == list(src.transform.to_gdal())
            assert len(frame["records"]) == 2
            assert all(r["interval_start_utc"] is None and r["interval_end_utc"] is None for r in frame["records"])
            for name, dataset, scale in (("rate",rate,1.), ("derived_depth",depth,.5)):
                info = frame["measurements"][name]
                area = coverage[info["coverage"]]
                values = dataset.read(band)
                np.testing.assert_array_equal(np.isfinite(values), grid.valid)
                expected = (weights[:,grid.valid].T @ rates)*scale/area[grid.valid]
                np.testing.assert_allclose(values[grid.valid], expected, rtol=1e-12, atol=1e-12)
                assert dataset.units[band-1] == ("mm/h" if name == "rate" else "mm")
                integral = np.sum(values[grid.valid]*area[grid.valid])/1000
                assert integral == pytest.approx(info["source_integral"], abs=1e-7, rel=1e-11)
                oracle = (rates[0]*independent.sum()+rates[1]*(8022600-independent.sum()))*scale/1000
                assert abs(integral-oracle) < .0001


def test_imd_outside_centre_daily_product(local_grid, tmp_path):
    raw = ROOT/"data/rainfall/raw/imd/17092026.grd"
    if not raw.exists():
        pytest.skip("local IMD daily grid unavailable")
    grid, dem = local_grid
    folder, manifest = open_local_snapshot(IMD, grid, dem, tmp_path)
    frame, = manifest["frames"]
    record, = frame["records"]
    assert record["geometry"]["center"] == [77.75, 13.0]
    assert record["geometry"]["footprint"] == [77.625,12.875,77.875,13.125]
    x, y = transform("EPSG:4326", grid.crs, [77.75], [13])
    r, c = rasterio.transform.rowcol(grid.affine, x[0], y[0])
    assert not (0 <= r < 97 and 0 <= c < 95)
    assert record["measurement_type"] == "daily_accumulation" and record["reported_date"] == "2026-09-17"
    assert record["interval_start_utc"] is record["interval_end_utc"] is None
    raw_value = float(np.fromfile(raw, dtype="<f4").reshape(281,241)[172,111])
    info = frame["measurements"]["daily_depth"]
    with rasterio.open(folder/info["coverage"]) as ds:
        check_saved_coverage(ds, grid)
    with rasterio.open(folder/info["raster"]) as ds:
        values = ds.read(1)
        assert ds.count == 1 and ds.units == ("mm",)
        np.testing.assert_array_equal(values[grid.valid], raw_value)
        assert np.isnan(values[~grid.valid]).all()
        assert info["mapped_integral"] == pytest.approx(raw_value*8022600/1000, abs=1e-7, rel=0)
