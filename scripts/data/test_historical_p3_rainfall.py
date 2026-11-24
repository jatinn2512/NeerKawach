"""P3 historical adapter checks and a standalone replay against the immutable local archive."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import historical_p3_rainfall as hist
import run_surface_routing as runner
from run_manifest import checksum

ROOT = runner.ROOT
BUNDLE = Path("data/rainfall/temporal/068d3d77a49c5602/manifest.json")
EVENT = "bellandur_2022-09-01"
ALTERNATIVE = "bellandur_2022-08-31"
CONFIG = Path("config/surface_routing.json")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_metres_once_and_nodata_separate_from_dry():
    valid = np.array([[True, True, False]])
    field, volume = hist.convert_band(np.array([[1., 0., np.nan]]), valid, np.array([900., 900.]))
    assert field.dtype == np.float64 and field.tolist() == [[0.001, 0., hist.EXCLUDED]]
    assert hist.EXCLUDED < 0 and volume == .9
    for broken in ([np.nan, 0., np.nan], [-1., 0., np.nan], [1., 0., 0.]):
        with pytest.raises(ValueError, match="nodata or negative"):
            hist.convert_band(np.array([broken]), valid, np.array([900., 900.]))


@pytest.mark.parametrize("problem", ["gap","partial","crs","shift","shape"])
def test_spatial_validation_on_small_grid(tmp_path, problem):
    valid = np.array([[True, False]])
    affine = from_origin(0,30,30,30)
    crs = rasterio.crs.CRS.from_epsg(32643)
    grid = hist.WorkingGrid(crs, affine, valid)
    file = tmp_path/"coverage.tif"
    width = 3 if problem == "shape" else 2
    with rasterio.open(file,"w",driver="GTiff",count=3,height=1,width=width,dtype="float64",nodata=np.nan,
                       crs="EPSG:4326" if problem=="crs" else crs,
                       transform=from_origin(1,30,30,30) if problem=="shift" else affine) as ds:
        for i, (name, unit, value) in enumerate(zip(("covered_area_m2","coverage_fraction","source_valid"),
                                                     ("m2","1","1"),(900.,1.,1.)), 1):
            values = np.full((1,width),np.nan)
            values[0,0] = value
            if problem=="gap" and i==3:
                values[0,0] = 0.
            if problem=="partial" and i==1:
                values[0,0] = 899.
            ds.write(values,i)
            ds.set_band_description(i,name)
            ds.set_band_unit(i,unit)
    with pytest.raises(ValueError, match="alignment|full source coverage"):
        hist.read_coverage(file,grid)


def test_invalid_mode_never_requests_synthetic_data(monkeypatch):
    monkeypatch.setattr(runner, "load_rainfall", lambda *args: pytest.fail("selected synthetic fallback"))
    for kwargs in ({"event": EVENT}, {"temporal_manifest": BUNDLE},
                   {"event": EVENT, "temporal_manifest": BUNDLE, "rainfall": "synthetic.json"}):
        with pytest.raises(ValueError, match="historical mode"):
            runner.run(argparse.Namespace(**kwargs))


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    """Copy only published inputs into an isolated repo for write/failure tests."""
    if not (ROOT/BUNDLE).is_file():
        pytest.skip("Task 2.4 delivery unavailable")
    root = tmp_path_factory.mktemp("historical")
    shutil.copytree((ROOT/BUNDLE).parent, (root/BUNDLE).parent)
    names = set(read(ROOT/BUNDLE)["input_sha256"])
    for name in names:
        destination = root/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,destination)
    return root


def runner_root(monkeypatch, root):
    for key, name in (("ROOT","."),("ROUTING_CONFIG_PATH","config/surface_routing.json"),
                      ("STUDY_AREA_PATH","config/study_area.json"),("WORKING_DIR","data/surface_routing/input"),
                      ("RESULTS_DIR","data/surface_routing/results")):
        monkeypatch.setattr(runner,key,root/name if name != "." else root)


def test_alternative_event_and_unknown_id(archive):
    forcing = hist.load_event(archive,archive/BUNDLE,ALTERNATIVE,archive/CONFIG)
    assert len(forcing.steps) == 228 and forcing.metadata["source_observations"] == 38
    assert forcing.metadata["raster_volume_m3"] == pytest.approx(51619.99956992651,abs=1e-7,rel=0)
    assert forcing.metadata["excluded_cells"] == 301 and forcing.metadata["valid_cells"] == 8914
    assert forcing.steps[-1].timestamp == "relative_end_68400s"
    with pytest.raises(ValueError,match="unknown historical event"):
        hist.load_event(archive,archive/BUNDLE,"unpublished",archive/CONFIG)


def event_files(root):
    bundle = read(root/BUNDLE)
    path, = [(root/BUNDLE).parent/p for p in bundle["events"] if read((root/BUNDLE).parent/p)["id"] == EVENT]
    e = read(path)
    spatial = read(root/e["mapped_manifest"])
    frames = {f["timestamp_utc"]:f for f in spatial["frames"]}
    audit = read(path.parent.parent/"conservation.json")["frames"]
    return path, e, read(path.parent/e["step_index"]), frames, audit


@pytest.mark.parametrize("problem", ["count","duplicate","duration","source_label","native_pixel","interval_order"])
def test_reject_inconsistent_clock_and_provenance(archive,problem):
    _,event,rows,frames,audit = event_files(archive)
    selected = deepcopy(event)
    if problem=="count":
        rows.pop()
    elif problem=="duplicate":
        rows[1]["band"] = 1
    elif problem=="duration":
        rows[3]["relative_end_seconds"] += 1
    elif problem=="source_label":
        rows[0]["source_label"] = rows[-1]["source_label"]
    elif problem=="native_pixel":
        frames[rows[0]["timestamp_utc"]]["records"][1]["geometry"]["row"] += 1
    else:
        event["intervals"].reverse()
    with pytest.raises(ValueError):
        hist.verify_steps(event,selected,rows,frames,audit)


@pytest.mark.parametrize("problem", ["checksum","missing","band_count"])
def test_invalid_products_fail_before_simulation(archive,tmp_path,monkeypatch,problem):
    runner_root(monkeypatch,archive)
    monkeypatch.setattr(runner,"simulate",lambda *args: pytest.fail("invalid event reached P3"))
    monkeypatch.setattr(runner,"load_rainfall",lambda *args: pytest.fail("invalid event used fixture"))
    # Keep each modified snapshot independent, including deliberately re-signed malformed inputs.
    source = archive/BUNDLE
    folder = tmp_path/source.parent.name
    shutil.copytree(source.parent,folder)
    bundle = read(folder/source.name)
    rel = next(p for p in bundle["events"] if read(folder/p)["id"] == EVENT)
    event_file = folder/rel
    event = read(event_file)
    raster = event_file.parent/event["depth_raster"]
    if problem=="missing":
        raster.unlink()
    elif problem=="checksum":
        with raster.open("ab") as f:
            f.write(b"altered")
    else:
        with rasterio.open(raster) as src:
            profile, data, tags = src.profile, src.read(1), src.tags()
        profile["count"] = 1
        with rasterio.open(raster,"w",**profile) as ds:
            ds.write(data,1)
            ds.update_tags(**tags)
        event["output_sha256"][raster.name] = checksum(raster)
        event_file.write_text(json.dumps(event),encoding="utf-8")
        bundle["output_sha256"][rel] = checksum(event_file)
        bundle["output_sha256"][raster.relative_to(folder).as_posix()] = checksum(raster)
        (folder/source.name).write_text(json.dumps(bundle),encoding="utf-8")
        new_folder = tmp_path/checksum(folder/source.name)[:16]
        folder.rename(new_folder)
        folder = new_folder
    before = set((archive/"data/runs").glob("*/manifest.json"))
    with pytest.raises((FileNotFoundError,ValueError)):
        runner.run(argparse.Namespace(temporal_manifest=folder/source.name,event=EVENT))
    record, = set((archive/"data/runs").glob("*/manifest.json"))-before
    failed = read(record)
    assert failed["status"] == "failed" and failed["event_id"] == EVENT
    assert failed["failure_reason"] and not failed["outputs"]
    if problem=="band_count":
        assert "raster bands" in failed["failure_reason"]


def assert_saved_peaks(root, summary):
    maxima = None
    for row in summary["time_series"]:
        with rasterio.open(root / row["depth_file"]) as ds:
            frame = ds.read(1)
        maxima = frame.copy() if maxima is None else np.maximum(maxima, frame)
    with rasterio.open(root / summary["outputs"]["max_depth"]) as ds:
        assert ds.tags()["STATISTIC"] == "cellwise_maximum_over_saved_timesteps"
        assert "MAXIMUM_DEPTH_TIMESTAMP" not in ds.tags()
        np.testing.assert_array_equal(ds.read(1), maxima)
        assert (ds.read_masks(1) == 0).sum() == 301
    peak = summary["time_series"][summary["maximum_depth_index"]]
    assert summary["domain_peak_depth_file"] == peak["depth_file"]
    with rasterio.open(root / peak["depth_file"]) as ds:
        assert ds.tags()["TIMESTAMP"] == peak["timestamp"] == summary["maximum_depth_timestamp"]
        assert ds.read(1).max() == maxima.max() == np.float32(summary["maximum_depth_m"])


def test_complete_primary_p3_replay(archive,monkeypatch):
    runner_root(monkeypatch,archive)
    monkeypatch.setattr(runner,"load_rainfall",lambda *args: pytest.fail("synthetic fallback"))
    summary = runner.run(argparse.Namespace(temporal_manifest=archive/BUNDLE,event=EVENT))
    run = archive/"data/runs"/summary["run_id"]
    record = read(run/"manifest.json")
    rows = summary["time_series"]
    source = record["configuration"]["rainfall"]
    assert record["status"]=="succeeded" and all(v["passed"] for v in record["validations"])
    assert record["simulation_start"] is record["simulation_end"] is None
    assert source["native_resolution_m"] == [4000.] and source["relative_end_seconds"] == 68400
    assert len(rows) == 228 and summary["steps"] == 228
    assert [r["relative_end_seconds"] for r in rows] == list(range(300,68401,300))
    assert [r["band"] for r in rows] == list(range(1,229))
    assert len({r["timestamp_utc"] for r in rows}) == 38
    assert len({i["native_file"] for i in source["intervals"]}) == 38
    assert all(len(i["native_pixels"]) == 2 for i in source["intervals"])
    with rasterio.open(archive/source["target_grid"]["dem"]) as dem, rasterio.open(archive/source["allocated_raster"]) as ds:
        valid = dem.read_masks(1)>0
        assert valid.sum()==8914 and (~valid).sum()==301
        for row in rows:
            with rasterio.open(archive/row["depth_file"]) as out:
                assert (out.crs,out.shape,out.transform) == (dem.crs,dem.shape,dem.transform)
                np.testing.assert_array_equal(out.read_masks(1)>0,valid)
                assert out.tags()["TIMESTAMP"] == row["timestamp"]
            raw = ds.read(row["band"])
            np.testing.assert_array_equal(np.isfinite(raw),valid)
            assert row["rainfall_input_m3"] == pytest.approx(float(raw[valid].sum()*900/1000),abs=1e-7,rel=0)
    assert summary["total_rainfall_input_m3"] == pytest.approx(34897.79656418666,abs=1e-7,rel=0)
    budget = record["water_budget"]
    residual = (budget["initial_stored_water_m3"]+summary["total_rainfall_input_m3"]
                -budget["total_coefficient_loss_m3"]-budget["total_infiltration_loss_m3"]
                -budget["boundary_outflow_m3"]-budget["final_stored_water_m3"])
    assert abs(residual) <= summary["parameters"]["mass_balance_tolerance_m3"]
    assert all(checksum(archive/item["path"])==item["sha256"] for item in record["outputs"])
    terrain = record["terrain_hydrology"]
    direction = terrain["products"]["flow_direction"]
    assert direction["sha256"] == checksum(archive / direction["file"])
    assert direction["file"].startswith(f"data/runs/{summary['run_id']}/terrain/")
    assert terrain["source_dem_sha256"] == checksum(archive / source["target_grid"]["dem"])
    assert_saved_peaks(archive, summary)
    rain_free_depths = []
    for row in rows[216:228]:
        assert row["rainfall_input_m3"] == 0
        with rasterio.open(archive / row["depth_file"]) as ds:
            rain_free_depths.append(ds.read(1)[[75, 75, 76], [63, 64, 64]])
    wet = np.array(rain_free_depths) >= 0.05
    assert not np.any(np.all(wet[1:] != wet[:-1], axis=0))


@pytest.mark.parametrize("run_scoped", [False, True])
def test_default_synthetic_runner_in_isolation(tmp_path,monkeypatch,run_scoped):
    runner_root(monkeypatch,tmp_path)
    original_inputs = runner.P2_INPUTS
    monkeypatch.setattr(runner,"P2_INPUTS",{k:tmp_path/p.relative_to(ROOT) for k,p in original_inputs.items()})
    for p in [*original_inputs.values(), ROOT/CONFIG, ROOT/"config/study_area.json",
              ROOT/"data/surface_routing/tests/synthetic_rainfall.json"]:
        target = tmp_path/p.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target)
    actual = runner.run(argparse.Namespace(rainfall=None,rainfall_timestep_seconds=None,run_scoped=run_scoped))
    assert actual["steps"]==12 and actual["rainfall"]["source"]=="synthetic_test"
    assert actual["total_rainfall_input_m3"] == pytest.approx(320904,abs=1e-7,rel=0)
    assert actual["final_stored_water_m3"] == pytest.approx(238003.8,abs=1e-7,rel=0)
    assert abs(actual["mass_balance_residual_m3"]) <= actual["parameters"]["mass_balance_tolerance_m3"]
    assert_saved_peaks(tmp_path, actual)
    assert not runner.RESULTS_DIR.exists() and not runner.WORKING_DIR.exists()
    record = read(tmp_path / "data/runs" / actual["run_id"] / "manifest.json")
    assert record["status"] == "succeeded"
    assert record["terrain_hydrology"] == actual["terrain_hydrology"]
    assert all(Path(item["path"]).parts[:3] == ("data", "runs", actual["run_id"]) for item in record["outputs"])
