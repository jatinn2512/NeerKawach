"""Validate a published MOSDAC temporal event before passing its allocated bands to P3."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.rainfall import temporal
from app.rainfall.spatial import WorkingGrid
from run_manifest import checksum
from surface_routing_core import RainfallStep

VOLUME_ATOL_M3 = 1e-7
EXCLUDED = -1.0  # Finite sentinel, outside the terrain mask only. P3 masks it before arithmetic.


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def below(base, name):
    path = (base / name).resolve()
    path.relative_to(base.resolve())
    return path


class VerifiedFiles:
    def __init__(self):
        self.hashes = {}

    def check(self, path, expected):
        if path not in self.hashes:
            self.hashes[path] = checksum(path)
        require(self.hashes[path] == expected, f"checksum mismatch for {path.name}")
        return path


@dataclass
class HistoricalForcing:
    steps: list[RainfallStep]
    metadata: dict
    inputs: list[Path]
    grid: dict
    dem_path: Path


def aligned(dataset, grid):
    require((dataset.shape, dataset.crs, dataset.transform) == (grid.valid.shape, grid.crs, grid.affine),
            f"raster alignment mismatch for {Path(dataset.name).name}")


def read_coverage(path, grid):
    with rasterio.open(path) as ds:
        aligned(ds, grid)
        require(ds.descriptions == ("covered_area_m2", "coverage_fraction", "source_valid")
                and ds.units == ("m2", "1", "1"), "unexpected spatial coverage bands")
        area, fraction, source_valid = ds.read(masked=True).astype("float64").filled(np.nan)
    valid = grid.valid
    for layer in (area, fraction, source_valid):
        require(np.array_equal(np.isfinite(layer), valid), "source coverage mask differs from terrain")
    require(np.all(source_valid[valid] == 1) and np.allclose(fraction[valid], 1, atol=1e-11, rtol=0)
            and np.allclose(area[valid], grid.cell_area, atol=1e-6, rtol=0),
            "historical P3 requires full source coverage in every valid DEM cell")
    return area[valid]


def convert_band(depth_mm, valid, covered_area):
    require(np.array_equal(np.isfinite(depth_mm), valid) and np.all(depth_mm[valid] >= 0),
            "rainfall nodata or negative depth on the working grid")
    mm = depth_mm[valid]
    # Separate raw-mm/covered-area integration from P3's full-cell, metre-based sum.
    volume = float(np.sum(mm*covered_area, dtype=np.float64)) / 1000
    field = np.full(valid.shape, EXCLUDED, dtype=np.float64)
    field[valid] = mm / 1000
    return field, volume


def verify_steps(event, selected, rows, frames, audit):
    labels = temporal.nominal_labels(selected["first_label_utc"], selected["last_label_utc"])
    expected = list(temporal.relative_steps(labels))
    require(event["first_label_utc"] == labels[0] and event["last_label_utc"] == labels[-1]
            and event["step_seconds"] == temporal.STEP and event["nominal_source_duration_seconds"] == temporal.CADENCE
            and event["source_observations"] == len(event["intervals"]) == len(labels)
            and event["generated_steps"] == len(rows) == len(expected)
            and event["relative_start_seconds"] == 0 and event["relative_end_seconds"] == len(rows)*temporal.STEP,
            "event band count, source labels or relative duration disagree with the configured window")
    for i, (label, parent) in enumerate(zip(labels, event["intervals"])):
        original, verified = frames[label], audit[label]
        require(parent["timestamp_utc"] == label and parent["source_interval_index"] == i
                and parent["relative_start_seconds"] == i*temporal.CADENCE
                and parent["relative_end_seconds"] == (i+1)*temporal.CADENCE
                and parent["mapped_band"] == original["band"] and parent["source_label"] == original["source_label"]
                and parent["native_file"] == original["source_file"]
                and all(parent[k] == v for k, v in verified.items()), "inconsistent source interval provenance")
        records = original["records"]
        pixels = {(p["row"], p["column"], p["source_record_id"]) for p in parent["native_pixels"]}
        mapped = {(r["geometry"]["row"], r["geometry"]["column"], r["source_record_id"]) for r in records}
        require(pixels == mapped and len(pixels) == len(records) == len(parent["native_pixels"]) == 2
                and all(r["observed"] and not r["forecast"] and not r["missing"] and r["timestamp_utc"] == label
                        and r["source_file"] == parent["native_file"] and r["source"] == temporal.SOURCE for r in records),
                "native MOSDAC observation or pixel identity mismatch")
    for row, clock in zip(rows, expected):
        parent = event["intervals"][clock["source_interval_index"]]
        require(all(row[k] == v for k,v in clock.items())
                and all(row[k] == parent[k] for k in ("source_label","mapped_band","coverage_raster"))
                and row["absolute_interval_status"] == "unknown" and row["measurement_type"] == "allocated_depth"
                and row["assumption"] == event["assumption"], "invalid step index, relative clock or source label")


def load_event(root, manifest_path, event_id, config_path):
    root, manifest_path = root.resolve(), manifest_path.resolve()
    files = VerifiedFiles()
    bundle = read(manifest_path)
    bundle_dir = manifest_path.parent
    digest = checksum(manifest_path)
    require(bundle_dir.name == digest[:16] and bundle["status"] == "complete",
            "temporal manifest differs from its published snapshot identity")
    files.check(manifest_path, digest)

    def product(path):
        name = path.relative_to(bundle_dir).as_posix()
        return files.check(path, bundle["output_sha256"][name])

    def input_path(name):
        return files.check(below(root, name), bundle["input_sha256"][name])

    configs = read(input_path("config/rainfall_events.json"))["temporal_processing"]
    candidates = [e for e in configs["events"] if e["id"] == event_id]
    require(len(candidates) == 1 and configs["source"] == temporal.SOURCE, "unknown historical event")
    matches = []
    for entry in bundle["events"]:
        p = product(below(bundle_dir, entry))
        candidate = read(p)
        if candidate["id"] == event_id:
            matches.append((p, candidate))
    require(len(matches) == 1, "event must occur exactly once in the temporal manifest")
    event_path, event = matches[0]
    require(event["source"] == temporal.SOURCE and event["source_completeness"] == "complete"
            and not event["missing_labels"] and event["assumption"] == bundle["assumption"] == temporal.ASSUMPTION
            and event["clock"] == "relative_seconds" and event["absolute_interval_status"] == "unknown"
            and event["interval_start_utc"] is event["interval_end_utc"] is None, "ineligible historical forcing")
    event_dir = event_path.parent
    def event_product(key):
        path = product(below(event_dir, event[key]))
        return files.check(path, event["output_sha256"][event[key]])

    raster, index = event_product("depth_raster"), event_product("step_index")
    rows = read(index)
    spatial_path = input_path(event["mapped_manifest"])
    files.check(spatial_path, event["mapped_manifest_sha256"])
    spatial = read(spatial_path)
    target = event["target_grid"]
    require(spatial["target_grid"] == target and spatial["source_id"] == temporal.SOURCE
            and spatial["processing_status"] == "complete", "historical working grid or source mismatch")
    # The 2.4 bundle lists the per-source conservation product among its hashed outputs.
    audit_paths = [below(bundle_dir, name) for name in bundle["output_sha256"]
                   if Path(name).name == "conservation.json" and below(bundle_dir, name).parent == event_dir.parent]
    require(len(audit_paths) == 1, "expected one source conservation product")
    audit = read(product(audit_paths[0]))
    require(audit["mapped_manifest"] == event["mapped_manifest"] and audit["assumption"] == event["assumption"],
            "conservation reference mismatch")
    frames = {f["timestamp_utc"]: f for f in spatial["frames"]}
    verify_steps(event, candidates[0], rows, frames, audit["frames"])
    gap_path = (event_dir / event["missing_inventory"]).resolve()
    gaps = read(product(gap_path))
    missing = {label for gap in gaps["missing_runs"] for label in gap["labels"]}
    require(not missing.intersection(row["timestamp_utc"] for row in rows), "event crosses a source gap")
    for parent in event["intervals"]:
        name = parent["native_file"]
        files.check(input_path(name), spatial["input_sha256"][name])

    dem, grid_path = input_path(target["dem"]), input_path(target["grid_metadata"])
    grid = WorkingGrid.read(dem, grid_path)
    declared = read(grid_path)
    cfg = read(files.check(config_path, bundle["input_sha256"][config_path.relative_to(root).as_posix()]))
    require(target["crs"] == cfg["working_crs"] == str(grid.crs) and cfg["timestep_seconds"] == temporal.STEP
            and list(grid.valid.shape) == target["shape_rows_columns"]
            and list(grid.affine.to_gdal()) == target["transform_gdal"]
            and target["pixel_size_m"] == [cfg["target_resolution_m"]]*2
            and grid.cell_area == target["cell_area_m2"]
            and grid.cell_area*int(grid.valid.sum()) == target["valid_domain_area_m2"], "invalid target geometry")
    mask_file = input_path(event["dem_valid_raster"])
    require(mask_file == below(spatial_path.parent, target["valid_mask"]), "unexpected DEM mask reference")
    with rasterio.open(mask_file) as ds:
        aligned(ds, grid)
        require(np.array_equal(ds.read(1), grid.valid.astype("uint8")), "published DEM mask mismatch")

    areas = {}
    for interval in event["intervals"]:
        name = interval["coverage_raster"]
        coverage = frames[interval["timestamp_utc"]]["measurements"]["derived_depth"]["coverage"]
        require(below(root, name) == below(spatial_path.parent, coverage), "unexpected coverage reference")
        if name not in areas:
            path = files.check(input_path(name), spatial["output_sha256"][coverage])
            areas[name] = read_coverage(path, grid)
    steps, volumes = [], []
    with rasterio.open(raster) as ds:
        aligned(ds, grid)
        tags = ds.tags()
        require(ds.count == len(rows) and ds.units == ("mm",)*ds.count and ds.dtypes == ("float64",)*ds.count
                and all(tags.get(k) == event[k] for k in ("source","clock","assumption","absolute_interval_status"))
                and tags.get("event") == event_id and tags.get("measurement_type") == "allocated_depth"
                and tags.get("index") == index.name and ds.nodata is not None and math.isnan(ds.nodata),
                "invalid temporal raster bands, units or identity")
        for row, description in zip(rows, ds.descriptions):
            require(description == f"relative_{row['relative_start_seconds']}s", "raster band order mismatch")
            mm = ds.read(row["band"], masked=True).filled(np.nan)
            field, volume = convert_band(mm, grid.valid, areas[row["coverage_raster"]])
            expected = audit["frames"][row["timestamp_utc"]]["grid"]["step_volume_m3"]
            require(abs(volume-expected) <= VOLUME_ATOL_M3, "step volume differs from temporal conservation audit")
            label = f"relative_end_{row['relative_end_seconds']}s"
            steps.append(RainfallStep(label, field))
            volumes.append(volume)
    total = math.fsum(volumes)
    require(all(abs(total-event[k]) <= VOLUME_ATOL_M3 for k in ("allocated_volume_m3","source_volume_m3")),
            "integrated raster volume differs from the temporal event")
    metadata = {k:event[k] for k in ("id","source","provider","assumption","allocation","target_grid","step_seconds",
                "relative_start_seconds","relative_end_seconds","first_label_utc","last_label_utc","clock",
                "absolute_interval_status","interval_start_utc","interval_end_utc","source_observations","generated_steps",
                "allocated_volume_m3","source_volume_m3","mapped_manifest","mapped_manifest_sha256","rate_measurement_period")}
    metadata.update(mode="historical_observation_derived", temporal_manifest=manifest_path.relative_to(root).as_posix(),
                    temporal_manifest_sha256=digest, event_manifest=event_path.relative_to(root).as_posix(),
                    step_index=index.relative_to(root).as_posix(), allocated_raster=raster.relative_to(root).as_posix(),
                    native_resolution_m=sorted({r["native_resolution_m"] for i in event["intervals"]
                                                for r in frames[i["timestamp_utc"]]["records"]}),
                    intervals=event["intervals"], bands=rows, raster_volume_m3=total, per_step_volume_m3=volumes,
                    valid_cells=int(grid.valid.sum()), excluded_cells=int((~grid.valid).sum()),
                    input_unit="mm", engine_unit="m", excluded_engine_sentinel=EXCLUDED, volume_tolerance_m3=VOLUME_ATOL_M3)
    return HistoricalForcing(steps, metadata, list(files.hashes), declared["working_grid"], dem)
