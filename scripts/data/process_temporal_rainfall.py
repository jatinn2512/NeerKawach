"""Build offline relative-time MOSDAC rainfall events from normalized records and mapped fields."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.rainfall import temporal
from app.rainfall.registry import REGISTRY_PATH, load_registry, relative_path
from app.rainfall.resolver import source_files
from app.services.rainfall import load_series
from run_manifest import checksum

RAINFALL = ROOT / "data/rainfall"
EVENT_CONFIG = ROOT / "config/rainfall_events.json"
ROUTING_CONFIG = ROOT / "config/surface_routing.json"
VERSION = "2.4.1"
IMD = "imd_ncmrwf_gpm_merged_daily"
NATIVE_SOURCES = (IMD, "arg_aws", "open_meteo_precipitation_forecast", "imerg")
ATOL_MM = 1e-12
ATOL_M3 = 1e-7
RTOL = 1e-11


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")


def mapped_snapshot(source, inputs):
    base = RAINFALL / "mapped" / source
    pointer = read(base / "latest.json")
    path = base / pointer["manifest"]
    manifest = read(path)
    if (checksum(path) != pointer["manifest_sha256"] or manifest["source_id"] != source
            or manifest["processing_status"] != "complete"):
        raise ValueError(f"invalid spatial manifest for {source}")
    pinned = {ROOT/name: digest for name, digest in manifest["input_sha256"].items()}
    pinned.update({path.parent/name: digest for name, digest in manifest["output_sha256"].items()})
    for file, digest in pinned.items():
        if checksum(file) != digest:
            raise ValueError(f"spatial snapshot checksum mismatch for {file.name}")
    inputs.update(pinned)
    inputs.add(path)
    return path, manifest


def comparison(frame, pixels):
    """Reject stale normalized-to-mapped joins, including differing pixel identities or values."""
    native = {(r["geometry"]["row"], r["geometry"]["column"]): r for r in frame["records"]}
    if len(native) != len(frame["records"]) or native.keys() != pixels.keys():
        raise ValueError("normalized and mapped native pixel inventories disagree")
    fields = ("source", "product", "source_file", "source_record_id", "source_label", "timestamp_utc",
              "measurement_type", "original_value", "original_unit", "derived_value", "derived_unit",
              "interval_start_utc", "interval_end_utc", "missing", "derivation")
    for key, record in pixels.items():
        if any(getattr(record, f) != native[key][f] for f in fields):
            raise ValueError(f"mapped and normalized observations disagree at {record.source_record_id}")


def grid_allocation(depth, rate, area, source_valid, terrain):
    """Verify per-cell depth, equivalent rate, and covered-area volume before writing."""
    valid = terrain & (source_valid == 1)
    if (not np.array_equal(valid, np.isfinite(depth)) or not np.array_equal(valid, np.isfinite(rate))
            or not np.array_equal(valid, area > 0) or not np.isfinite(area[terrain]).all()
            or np.any(area[terrain] < 0)):
        raise ValueError("mapped rainfall, terrain and coverage disagree")
    step = temporal.step_depth(depth)
    selected = step[valid]
    if not np.allclose(selected, rate[valid]*temporal.STEP/3600, atol=ATOL_MM, rtol=RTOL):
        raise ValueError("mapped depth and rate allocations disagree")
    reconstructed = np.sum([selected]*temporal.COUNT, axis=0)
    error = float(np.max(np.abs(reconstructed-depth[valid]), initial=0))
    vol = float(np.sum(depth[valid]*area[valid])/1000)
    step_vol = float(np.sum(selected*area[valid])/1000)
    allocated = math.fsum([step_vol]*temporal.COUNT)
    if error > ATOL_MM or not math.isclose(allocated, vol, abs_tol=ATOL_M3, rel_tol=RTOL):
        raise ValueError("temporal depth or volume conservation failed")
    return step, {"covered_cells": int(valid.sum()), "source_volume_m3": vol, "step_volume_m3": step_vol,
                  "allocated_volume_m3": allocated, "volume_residual_m3": abs(allocated-vol),
                  "max_cell_depth_residual_mm": error}


def native_catalog(directory, configs, as_of, inputs):
    for source in NATIVE_SOURCES:
        config = configs[source]
        series, files = load_series(source, config, as_of)
        inputs.update(ROOT / f for f in files)
        for group in source_files(config):
            inputs.update(group)
        for capture in series.captures:
            sidecar = RAINFALL / "metadata" / (capture["capture_id"]+".json")
            if sidecar.exists():
                inputs.add(sidecar)
        mapping = None
        if source == IMD:
            path, _ = mapped_snapshot(source, inputs)
            mapping = relative_path(path)
        write(directory/source/"native.json", {
            "processing_version": VERSION, "source": source, "provider": config["provider"],
            "processing": "native_resolution", "status": "available" if series.records else "unavailable",
            "allocated_steps": 0, "mapped_manifest": mapping, "archive_as_of_utc": as_of.isoformat(),
            "records": [r.as_dict() for r in series.records], "missing_labels": series.missing_labels,
            "captures": series.captures, "bundle_manifest": "../manifest.json"})


def read_field(datasets, frame, name):
    info = frame["measurements"][name]
    ds = datasets[info["raster"]]
    band = frame["band"]
    if ds.descriptions[band-1] != frame["timestamp_utc"] or ds.units[band-1] != info["unit"]:
        raise ValueError("mapped band has an inconsistent timestamp or unit")
    return ds.read(band)


def audit_archive(folder, spatial, frames, datasets, terrain):
    audit = {}
    for frame in spatial["frames"]:
        label = frame["timestamp_utc"]
        if label in audit:
            raise ValueError(f"duplicate mapped frame {label}")
        pixels = frames[label]
        comparison(frame, pixels)
        checks = []
        for (row, col), r in sorted(pixels.items()):
            checks.append({"row": row, "column": col, "source_record_id": r.source_record_id,
                           "native_rate_mm_h": r.original_value, "derived_depth_mm": r.derived_value,
                           **temporal.native_allocation(r)})
        rate = read_field(datasets, frame, "rate")
        depth = read_field(datasets, frame, "derived_depth")
        depth_info, rate_info = (frame["measurements"][key] for key in ("derived_depth", "rate"))
        coverage = depth_info["coverage"]
        if coverage != rate_info["coverage"]:
            raise ValueError("mapped depth and rate have different source support")
        area, _, valid = datasets[coverage].read()
        _, grid = grid_allocation(depth, rate, area, valid, terrain)
        if not math.isclose(grid["allocated_volume_m3"], depth_info["source_integral"],
                            abs_tol=ATOL_M3, rel_tol=RTOL):
            raise ValueError(f"allocation disagrees with independent spatial volume at {label}")
        audit[label] = {"source_label": frame["source_label"], "native_file": frame["source_file"],
                        "mapped_band": frame["band"], "coverage_raster": relative_path(folder/coverage),
                        "native_pixels": checks, "grid": grid,
                        "timestamp_convention": next(iter(pixels.values())).timestamp_convention}
    return audit


def event_product(directory, event, labels, audit, mapped_path, datasets, spatial):
    source = temporal.SOURCE
    out = directory/source/event["id"]
    out.mkdir(parents=True)
    first_frame = spatial["frames"][0]["measurements"]
    depth_name, rate_name = (first_frame[name]["raster"] for name in ("derived_depth", "rate"))
    ds = datasets[depth_name]
    steps = list(temporal.relative_steps(labels))
    profile = ds.profile.copy()
    profile.update(count=len(steps), dtype="float64", nodata=np.nan, interleave="band", predictor=3)
    field_path = out/"allocated_depth_mm.tif"
    with rasterio.open(field_path, "w", **profile) as writer:
        writer.update_tags(source=source, measurement_type="allocated_depth", assumption=temporal.ASSUMPTION,
                           unit="mm", clock="relative_seconds", absolute_interval_status="unknown",
                           event=event["id"], index="steps.json", processing_version=VERSION)
        for step in steps:
            label = step["timestamp_utc"]
            interval = audit[label]
            if (step["band"]-1) % temporal.COUNT == 0:
                values = temporal.step_depth(ds.read(interval["mapped_band"]))
            writer.write(values, step["band"])
            writer.set_band_unit(step["band"], "mm")
            writer.set_band_description(step["band"], f"relative_{step['relative_start_seconds']}s")
            step.update(source_label=interval["source_label"], mapped_band=interval["mapped_band"],
                        coverage_raster=interval["coverage_raster"], assumption=temporal.ASSUMPTION,
                        measurement_type="allocated_depth", absolute_interval_status="unknown")
    write(out/"steps.json", steps)
    totals = [audit[label]["grid"] for label in labels]
    intervals = [{"timestamp_utc": label, "source_interval_index": i,
                  "relative_start_seconds": i*temporal.CADENCE, "relative_end_seconds": (i+1)*temporal.CADENCE,
                  **audit[label]} for i, label in enumerate(labels)]
    write(out/"manifest.json", {
        "processing_version": VERSION, **event, "source": source, "provider": "MOSDAC / ISRO",
        "source_completeness": "complete", "missing_labels": [], "missing_inventory": "../inventory.json",
        "source_observations": len(labels), "generated_steps": len(steps), "intervals": intervals,
        "wet_observations": sum(any(p["status"] == "wet" for p in row["native_pixels"]) for row in intervals),
        "clock": "relative_seconds", "relative_start_seconds": 0, "relative_end_seconds": steps[-1]["relative_end_seconds"],
        "absolute_interval_status": "unknown", "interval_start_utc": None, "interval_end_utc": None,
        "rate_measurement_period": "unknown", "source_interval_seconds": None,
        "nominal_source_duration_seconds": temporal.CADENCE, "step_seconds": temporal.STEP,
        "assumption": temporal.ASSUMPTION, "allocation": "derived half-hour depth / 6; constant nominal intensity",
        "target_grid": spatial["target_grid"], "mapped_manifest": relative_path(mapped_path),
        "mapped_half_hour_depth_mm": relative_path(mapped_path.parent/depth_name),
        "mapped_native_rate_mm_h": relative_path(mapped_path.parent/rate_name),
        "dem_valid_raster": relative_path(mapped_path.parent/spatial["target_grid"]["valid_mask"]),
        "depth_raster": field_path.name, "step_index": "steps.json",
        "source_volume_m3": math.fsum(r["source_volume_m3"] for r in totals),
        "allocated_volume_m3": math.fsum(r["allocated_volume_m3"] for r in totals),
        "mapped_manifest_sha256": checksum(mapped_path), "bundle_manifest": "../../manifest.json",
        "output_sha256": {p.name: checksum(p) for p in (field_path, out/"steps.json")}})


def build(directory):
    configs = load_registry()["sources"]
    config = read(EVENT_CONFIG)
    settings = config["temporal_processing"]
    source = temporal.SOURCE
    if settings["source"] != source or read(ROUTING_CONFIG)["timestep_seconds"] != temporal.STEP:
        raise ValueError("configured source or computational timestep disagrees with MOSDAC allocation")
    analysis = next(e for e in config["events"] if e["id"] == settings["analysis_window_id"])
    as_of = datetime.fromisoformat(settings["archive_as_of_utc"])
    inputs = {REGISTRY_PATH, EVENT_CONFIG, ROUTING_CONFIG, ROOT/config["study_area"],
              Path(__file__).resolve(), Path(temporal.__file__).resolve()}
    series, files = load_series(source, configs[source], as_of)
    inputs.update(files)
    frames = temporal.group_pixels(series.records)
    mapped_path, spatial = mapped_snapshot(source, inputs)
    cfg = configs[source]
    first, last = cfg["historical_coverage_start_utc"], cfg["historical_coverage_end_utc"]
    if not (temporal.instant(analysis["start_utc"]) <= temporal.instant(first) <= temporal.instant(last)
            <= temporal.instant(analysis["end_utc"])):
        raise ValueError("configured analysis window does not contain the nominal source labels")
    inventory = temporal.inventory(frames, first, last)
    gaps = {label for r in inventory["missing_runs"] for label in r["labels"]}
    if (gaps != set(series.missing_labels) or gaps != set(spatial["missing_utc_labels"])
            or set(frames) != {f["timestamp_utc"] for f in spatial["frames"]}):
        raise ValueError("independent native label inventory disagrees with source or spatial archive")
    write(directory/source/"inventory.json", inventory)
    # Native geometry on the working domain determines the required pixel identities.
    expected_pixels = {tuple(p["pixel"]) for layout in spatial["layouts"].values() for p in layout["pixels"]
                       if p["valid_domain_area_m2"] > 0}
    with ExitStack() as stack:
        datasets = {name: stack.enter_context(rasterio.open(mapped_path.parent/name))
                    for name in spatial["output_sha256"]}
        mask = datasets[spatial["target_grid"]["valid_mask"]]
        if any((d.shape, d.crs, d.transform) != (mask.shape, mask.crs, mask.transform) for d in datasets.values()):
            raise ValueError("spatial products disagree on the target grid")
        audit = audit_archive(mapped_path.parent, spatial, frames, datasets, mask.read(1) == 1)
        write(directory/source/"conservation.json", {
            "processing_version": VERSION, "assumption": temporal.ASSUMPTION, "mapped_manifest": relative_path(mapped_path),
            "nominal_duration_seconds": temporal.CADENCE, "step_seconds": temporal.STEP,
            "source_rate_averaging_period": "unknown", "absolute_interval_status": "unknown",
            "tolerance": {"absolute_mm": ATOL_MM, "absolute_m3": ATOL_M3, "relative": RTOL}, "frames": audit})
        for event in settings["events"]:
            labels = temporal.event_labels(frames, event["first_label_utc"], event["last_label_utc"], expected_pixels)
            event_product(directory, event, labels, audit, mapped_path, datasets, spatial)
    native_catalog(directory, configs, as_of, inputs)
    write(directory/"manifest.json", {
        "processing_version": VERSION, "status": "complete", "analysis_window": analysis["id"],
        "archive_as_of_utc": settings["archive_as_of_utc"], "assumption": temporal.ASSUMPTION,
        "software": {"numpy": np.__version__, "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__},
        "events": [f"{source}/{e['id']}/manifest.json" for e in settings["events"]],
        "input_sha256": {relative_path(p): checksum(p) for p in sorted(inputs)},
        "output_sha256": {p.relative_to(directory).as_posix(): checksum(p) for p in sorted(directory.rglob("*")) if p.is_file()}})


def publish(output_root):
    """Expose the complete archive in a single atomic pointer update."""
    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".building-", dir=output_root) as tmp:
        stage = Path(tmp)/"products"
        stage.mkdir()
        build(stage)
        digest = checksum(stage/"manifest.json")
        destination = output_root / digest[:16]
        try:
            stage.rename(destination)
        except OSError:
            if not destination.is_dir() or checksum(destination/"manifest.json") != digest:
                raise
            for name, expected in read(stage/"manifest.json")["output_sha256"].items():
                if checksum(destination/name) != expected:
                    raise ValueError(f"published temporal product checksum mismatch for {name}")
        pointer = Path(tmp)/"latest.json"
        write(pointer, {"manifest": f"{destination.name}/manifest.json", "manifest_sha256": digest})
        pointer.replace(output_root/"latest.json")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(publish(RAINFALL/"temporal") / "manifest.json")


if __name__ == "__main__":
    main()
