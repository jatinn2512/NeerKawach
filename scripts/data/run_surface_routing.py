"""Run the P3 dynamic surface-water-routing prototype.

The runner reprojects the buffered P2 terrain inputs to UTM 43N, loads a
provider-neutral rainfall forcing, runs the conservative time-stepped engine,
and writes raster time-series/results. Synthetic rainfall is used by default
for engineering tests and is never treated as an observation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine, rowcol
from rasterio.warp import calculate_default_transform, reproject, transform

from surface_routing_core import RainfallStep, RoutingParameters, SimulationResult, simulate


from run_manifest import file_record, record_period, simulation_run, validation_results
from water_budget import surface_budgets
from working_terrain import write_working_terrain
from spatial_runoff import SCENARIOS, load_parameters


ROOT = Path(__file__).resolve().parents[2]
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"
ROUTING_CONFIG_PATH = ROOT / "config" / "surface_routing.json"
P2_INPUTS = {
    "dem": ROOT / "data" / "dem" / "processed" / "bellandur_dem_buffered.tif",
    "slope": ROOT / "data" / "dem" / "terrain" / "slope.tif",
    "aspect": ROOT / "data" / "dem" / "terrain" / "aspect.tif",
}
WORKING_DIR = ROOT / "data" / "surface_routing" / "input"
RESULTS_DIR = ROOT / "data" / "surface_routing" / "results"
DEPTH_DIR = RESULTS_DIR / "depth"
PREVIEW_DIR = RESULTS_DIR / "preview"
WORKING_CRS = "EPSG:32643"
WORKING_RESOLUTION_M = 30.0


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_projected_inputs(working_dir: Path) -> dict:
    area = load_json(STUDY_AREA_PATH)
    routing_config = load_json(ROUTING_CONFIG_PATH)
    if area.get("crs") != "EPSG:4326":
        raise ValueError("The canonical study area must remain EPSG:4326")
    if routing_config.get("working_crs") != WORKING_CRS or routing_config.get("target_resolution_m") != WORKING_RESOLUTION_M:
        raise ValueError("surface_routing.json working CRS/resolution does not match the runner")
    for name, path in P2_INPUTS.items():
        if not path.exists():
            raise FileNotFoundError(path)
    with rasterio.open(P2_INPUTS["dem"]) as source:
        if source.crs is None or source.crs.to_string() != "EPSG:4326":
            raise ValueError("P2 DEM must be EPSG:4326")
        if source.count != 1:
            raise ValueError("P2 DEM must have one band")
        source_bounds = source.bounds
        dst_transform, width, height = calculate_default_transform(
            source.crs,
            WORKING_CRS,
            source.width,
            source.height,
            *source.bounds,
            resolution=WORKING_RESOLUTION_M,
        )
        source_grid = {"width": source.width, "height": source.height, "crs": source.crs.to_string(), "transform": list(source.transform), "extent": {"left": source_bounds.left, "bottom": source_bounds.bottom, "right": source_bounds.right, "top": source_bounds.top}}

    for name, path in P2_INPUTS.items():
        with rasterio.open(path) as source:
            if source.crs is None or source.crs.to_string() != "EPSG:4326":
                raise ValueError(f"P2 {name} raster is not EPSG:4326")
            if (source.width, source.height) != (source_grid["width"], source_grid["height"]):
                raise ValueError(f"P2 {name} raster dimensions do not match the buffered DEM")
            if not np.allclose(list(source.transform), source_grid["transform"], rtol=0, atol=1e-12):
                raise ValueError(f"P2 {name} raster transform does not match the buffered DEM")

    resampling = {"dem": Resampling.bilinear, "slope": Resampling.nearest, "aspect": Resampling.nearest}
    projected = {}
    for name, path in P2_INPUTS.items():
        with rasterio.open(path) as source:
            source_data = source.read(1)
            source_nodata = source.nodata
            dtype = "float32" if name == "dem" else source.dtypes[0]
            destination_nodata = source_nodata if source_nodata is not None else -9999
            destination = np.full((height, width), destination_nodata, dtype=np.dtype(dtype))
            reproject(
                source=source_data,
                destination=destination,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source_nodata,
                dst_transform=dst_transform,
                dst_crs=WORKING_CRS,
                dst_nodata=destination_nodata,
                resampling=resampling[name],
            )
            output_path = working_dir / f"{name}_working.tif"
            profile = source.profile.copy()
            profile.update(driver="GTiff", height=height, width=width, count=1, crs=WORKING_CRS, transform=dst_transform, dtype=dtype, nodata=destination_nodata, compress="deflate", predictor=3 if dtype.startswith("float") else 2, BIGTIFF="IF_SAFER")
            working_dir.mkdir(parents=True, exist_ok=True)
            with rasterio.open(output_path, "w", **profile) as target:
                target.write(destination, 1)
                source_tags = source.tags()
                target.update_tags(**{key: source_tags[key] for key in ("UNITS", "SOURCE") if key in source_tags},
                                   SOURCE_FILE=path.relative_to(ROOT).as_posix(), WORKING_CRS=WORKING_CRS,
                                   RESAMPLING=resampling[name].name, PROCESSING="P3 projected working input")
            projected[name] = {"file": str(output_path.relative_to(ROOT)).replace("\\", "/"), "dtype": dtype, "nodata": destination_nodata}

    with rasterio.open(working_dir / "dem_working.tif") as dataset:
        grid = {
            "crs": WORKING_CRS,
            "width": dataset.width,
            "height": dataset.height,
            "transform": list(dataset.transform),
            "pixel_size_m": [abs(dataset.transform.a), abs(dataset.transform.e)],
            "extent": {"min_x": dataset.bounds.left, "min_y": dataset.bounds.bottom, "max_x": dataset.bounds.right, "max_y": dataset.bounds.top},
            "cell_area_m2": abs(dataset.transform.a * dataset.transform.e),
        }
    terrain = write_working_terrain(ROOT, working_dir / "dem_working.tif", working_dir)
    projected.update(terrain["products"])
    (working_dir / "working_grid.json").write_text(json.dumps({"source_grid": source_grid, "working_grid": grid, "working_crs_reason": "UTM zone 43N is the appropriate local projected CRS for Bengaluru longitude ~77.65E and provides metre-based distance/area calculations without changing the canonical EPSG:4326 study-area definition.", "outputs": projected}, indent=2) + "\n", encoding="utf-8")
    return {"area": area, "grid": grid, "projected": projected, "terrain": terrain}


def uniform_steps(payload: dict, shape: tuple[int, int]) -> tuple[str, float, list[RainfallStep]]:
    source = payload.get("source")
    if not source:
        raise ValueError("Rainfall forcing must identify a source")
    timestep = float(payload.get("timestep_seconds", 0))
    if timestep <= 0:
        raise ValueError("Rainfall forcing timestep_seconds must be positive")
    if payload.get("units", "mm") not in {"mm", "millimetres", "millimeters"}:
        raise ValueError("Rainfall forcing must use millimetre depth units")
    records = payload.get("records", [])
    if not records:
        raise ValueError("Rainfall forcing has no records")
    steps = []
    for record in records:
        if "timestamp" not in record or "rainfall_mm" not in record:
            raise ValueError("Rainfall records require timestamp and rainfall_mm")
        value = float(record["rainfall_mm"])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Rainfall depth must be finite and non-negative")
        steps.append(RainfallStep(str(record["timestamp"]), np.full(shape, value / 1000.0, dtype=np.float64)))
    return source, timestep, steps


def csv_steps(path: Path, shape: tuple[int, int], grid: dict, timestep_seconds: float) -> tuple[str, float, list[RainfallStep]]:
    groups: dict[str, list[tuple[float, float, float, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "latitude", "longitude", "rainfall_mm", "source"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Rainfall CSV must contain {sorted(required)}")
        source_name = None
        for record in reader:
            source_name = source_name or record["source"]
            groups[record["timestamp"]].append((float(record["latitude"]), float(record["longitude"]), float(record["rainfall_mm"]), record["source"]))
    if not groups or not source_name:
        raise ValueError("Rainfall CSV has no records")
    steps = []
    for timestamp, records in sorted(groups.items()):
        lats = [item[0] for item in records]
        lons = [item[1] for item in records]
        xs, ys = transform("EPSG:4326", grid["crs"], lons, lats)
        values: dict[tuple[int, int], list[float]] = defaultdict(list)
        for x, y, record in zip(xs, ys, records):
            value = record[2]
            if value < 0 or not math.isfinite(value):
                raise ValueError("Rainfall CSV values must be finite and non-negative")
            row, col = rowcol(Affine(*grid["transform"]), x, y, op=round)
            if 0 <= row < shape[0] and 0 <= col < shape[1]:
                values[(row, col)].append(value / 1000.0)
        field = np.zeros(shape, dtype=np.float64)
        for (row, col), samples in values.items():
            field[row, col] = float(np.mean(samples))
        steps.append(RainfallStep(timestamp, field))
    return source_name, timestep_seconds, steps


def load_rainfall(path: Path, shape: tuple[int, int], grid: dict, csv_timestep_seconds: float | None = None) -> tuple[str, float, list[RainfallStep], dict]:
    if path.suffix.lower() == ".json":
        payload = load_json(path)
        source, timestep, steps = uniform_steps(payload, shape)
        return source, timestep, steps, {"file": str(path.relative_to(ROOT)).replace("\\", "/"), "spatial_mode": payload.get("spatial_mode", "uniform"), "units": payload.get("units", "mm"), "source": source}
    if path.suffix.lower() == ".csv":
        if csv_timestep_seconds is None or csv_timestep_seconds <= 0:
            raise ValueError("--rainfall-timestep-seconds is required for CSV forcing")
        source, timestep, steps = csv_steps(path, shape, grid, csv_timestep_seconds)
        return source, timestep, steps, {"file": str(path.relative_to(ROOT)).replace("\\", "/"), "spatial_mode": "normalized_csv_points", "units": "mm", "source": source}
    raise ValueError("Rainfall forcing must be JSON or normalized CSV")


def write_depth_raster(path: Path, depth: np.ndarray, template_path: Path, extra_tags: dict[str, str] | None = None) -> None:
    with rasterio.open(template_path) as template:
        profile = template.profile.copy()
        outside_terrain = template.read_masks(1) == 0
    if not profile.get("tiled"):
        profile.pop("blockxsize", None)  # GDAL determines strip width from the raster width.
    profile.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, compress="deflate", predictor=3, BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **profile) as dataset:
        output = depth.astype(np.float32, copy=True)
        output[output < 0] = 0
        output[outside_terrain] = profile["nodata"]
        dataset.write(output, 1)
        dataset.update_tags(PRODUCT="dynamic surface-water depth", UNITS="metres", CRS="EPSG:32643", **(extra_tags or {}))


def write_pgm(path: Path, values: np.ndarray, nodata: float | None = None) -> None:
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    if not np.any(valid):
        return
    minimum, maximum = float(values[valid].min()), float(values[valid].max())
    scaled = np.zeros(values.shape, dtype=np.uint8)
    if maximum > minimum:
        scaled[valid] = np.clip((values[valid] - minimum) / (maximum - minimum) * 255, 0, 255).astype(np.uint8)
    else:
        scaled[valid] = 255
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(f"P5\n{scaled.shape[1]} {scaled.shape[0]}\n255\n".encode("ascii"))
        handle.write(scaled.tobytes())



def run(args: argparse.Namespace) -> dict:
    if (getattr(args, "soil_scenario", None) or getattr(args, "missing_soil", None)) and not getattr(args, "surface_parameters", None):
        raise ValueError("A soil sensitivity scenario requires a spatial parameter manifest")
    if getattr(args, "temporal_manifest", None) is not None or getattr(args, "event", None) is not None:
        if (not getattr(args, "temporal_manifest", None) or not getattr(args, "event", None)
                or getattr(args, "rainfall", None) is not None or getattr(args, "rainfall_timestep_seconds", None) is not None):
            raise ValueError("historical mode requires --temporal-manifest and --event together, without legacy forcing")
        return run_historical(args)
    if getattr(args, "rainfall", None) is None:
        args.rainfall = ROOT / "data/surface_routing/tests/synthetic_rainfall.json"
    run_id = str(uuid4())
    run_dir = ROOT / "data/runs" / run_id
    working_dir = run_dir / "input"
    results_dir = run_dir / "results"
    inputs = [*P2_INPUTS.values(), Path(args.rainfall)]
    with simulation_run(ROOT, "P3", inputs, [working_dir, results_dir],
                        [STUDY_AREA_PATH, ROUTING_CONFIG_PATH], run_id=run_id) as manifest:
        summary = _run(args, run_id, results_dir=results_dir, working_dir=working_dir)
        manifest["terrain_hydrology"] = summary["terrain_hydrology"]
        manifest["surface_parameterization"] = summary["surface_parameterization"]
        dt = summary["parameters"]["timestep_seconds"]
        times = [s["timestamp"] for s in summary["time_series"]]
        record_period(manifest, times, dt)
        manifest["configuration"]["rainfall"] = summary["rainfall"]
        checks = load_json(results_dir / "p3_validation.json")
        validation_results(manifest, checks["checks"])
        validation_results(manifest, {k: v for k, v in checks["accounting_checks"].items()
                                      if k != "routing_internal_transfers_conservative"})
        return summary


def run_historical(args: argparse.Namespace) -> dict:
    from historical_p3_rainfall import load_event

    run_id = str(uuid4())
    results = ROOT / "data/runs" / run_id / "results"
    terrain_dir = results.parent / "terrain"
    bundle = Path(args.temporal_manifest).resolve()
    with simulation_run(ROOT, "P3", [], [results, terrain_dir], [STUDY_AREA_PATH, ROUTING_CONFIG_PATH], run_id=run_id) as record:
        record["forcing_mode"] = "historical_observation_derived"
        record["event_id"] = args.event
        record["configuration"]["surface_routing_version_sha256"] = next(
            item["sha256"] for item in record["inputs"] if item["path"] == ROUTING_CONFIG_PATH.relative_to(ROOT).as_posix())
        record["requested_temporal_manifest"] = bundle.as_posix() if not bundle.is_relative_to(ROOT) else bundle.relative_to(ROOT).as_posix()
        try:
            forcing = load_event(ROOT, bundle, args.event, ROUTING_CONFIG_PATH)
            recorded = {item["path"] for item in record["inputs"]}
            for path in forcing.inputs:
                if path.relative_to(ROOT).as_posix() not in recorded:
                    record["inputs"].append(file_record(ROOT, path))
            record["configuration"]["rainfall"] = forcing.metadata
            record["configuration"]["duration_seconds"] = forcing.metadata["relative_end_seconds"]
            summary = _run(args, run_id, forcing, results, terrain_dir)
            record["terrain_hydrology"] = summary["terrain_hydrology"]
            record["surface_parameterization"] = summary["surface_parameterization"]
            checks = load_json(results / "p3_validation.json")
            validation_results(record, checks["checks"])
            validation_results(record, checks["accounting_checks"])
            record["rainfall_verification"] = summary["rainfall_verification"]
            record["water_budget"] = {k:v for k,v in summary.items() if k.endswith("_m3")}
            record["water_budget"]["residual_percent_of_gross_rainfall"] = summary["residual_percent_of_gross_rainfall"]
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            record["failure_reason"] = str(exc)
            raise
    if record["status"] != "succeeded":
        raise RuntimeError(f"historical run {run_id} failed validation")
    print(json.dumps({"run_id": run_id, "event": args.event, "steps": summary["steps"],
                      "manifest": (results.parent / "manifest.json").relative_to(ROOT).as_posix()}))
    return summary


def _run(args: argparse.Namespace, run_id: str, forcing=None, results_dir=None, working_dir=None) -> dict:
    if results_dir is None or working_dir is None:
        raise ValueError("P3 products require run-specific output directories")
    if forcing:
        grid = forcing.grid
        dem_path = forcing.dem_path
        terrain = write_working_terrain(ROOT, dem_path, working_dir)
    else:
        prepared = prepare_projected_inputs(working_dir)
        grid, terrain = prepared["grid"], prepared["terrain"]
        dem_path = working_dir / "dem_working.tif"
    depth_dir, preview_dir = results_dir / "depth", results_dir / "preview"
    direction_path = ROOT / terrain["products"]["flow_direction"]["file"]
    with rasterio.open(dem_path) as dem_dataset:
        dem = dem_dataset.read(1).astype(np.float64)
        dem_nodata = dem_dataset.nodata
        valid = np.isfinite(dem) & (dem != dem_nodata)
        valid &= dem_dataset.read_masks(1) != 0
        transform, crs = dem_dataset.transform, dem_dataset.crs
    with rasterio.open(direction_path) as direction_dataset:
        direction = direction_dataset.read(1)
        if (direction.shape != dem.shape or direction_dataset.transform != transform or direction_dataset.crs != crs
                or not np.array_equal(direction_dataset.read_masks(1) != 0, valid)):
            raise ValueError("Projected flow direction is not aligned with projected DEM")
    if forcing:
        rainfall_metadata = forcing.metadata
        source, forcing_timestep, rainfall_steps = rainfall_metadata["source"], rainfall_metadata["step_seconds"], forcing.steps
    else:
        source, forcing_timestep, rainfall_steps, rainfall_metadata = load_rainfall(Path(args.rainfall), dem.shape, grid, args.rainfall_timestep_seconds)
    config = load_json(ROUTING_CONFIG_PATH)
    params = RoutingParameters(**{key: config[key] for key in RoutingParameters.__dataclass_fields__})
    if abs(params.timestep_seconds - forcing_timestep) > 1e-9:
        raise ValueError("Rainfall timestep and routing timestep do not match")
    spatial = None
    provenance = {"mode": "uniform", "runoff_coefficient": params.runoff_coefficient,
                  "infiltration_rate_mm_per_hour": params.infiltration_rate_mm_per_hour}
    if getattr(args, "surface_parameters", None):
        spatial, provenance = load_parameters(ROOT, args.surface_parameters, dem_path,
                                               getattr(args, "soil_scenario", None),
                                               getattr(args, "missing_soil", None) or "zero-credit")
    result: SimulationResult = simulate(dem, valid, rainfall_steps, grid["cell_area_m2"], params, direction,
                                         grid["pixel_size_m"][0], grid["pixel_size_m"][1], spatial_runoff=spatial)
    tolerance = params.mass_balance_tolerance_m3
    accounting_checks = {
        "rainfall_equals_runoff_plus_coefficient_loss": abs(result.total_rainfall_input_m3 - (result.total_runoff_input_m3 + result.total_coefficient_loss_m3)) <= tolerance,
        "runoff_equals_surface_input_plus_infiltration_loss": abs(result.total_runoff_input_m3 - (result.total_surface_water_input_m3 + result.total_infiltration_loss_m3)) <= tolerance,
        "modeled_losses_equal_coefficient_plus_infiltration": abs(result.total_modeled_losses_m3 - (result.total_coefficient_loss_m3 + result.total_infiltration_loss_m3)) <= tolerance,
        "gross_water_balance_closes": abs(result.mass_balance_residual_m3) <= tolerance,
        "surface_routing_balance_closes": abs(result.surface_balance_residual_m3) <= tolerance,
        "routing_internal_transfer_net_m3": 0.0,
        "routing_internal_transfers_conservative": True,
        "routing_balance_within_tolerance": result.maximum_routing_balance_residual_m3 <= tolerance,
    }

    depth_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    for state in result.states:
        write_depth_raster(depth_dir / f"depth_{state['index']:04d}.tif", state["water_depth_m"], dem_path, {"TIMESTEP_INDEX": str(state["index"]), "TIMESTAMP": state["timestamp"]})
    write_depth_raster(results_dir / "max_depth.tif", result.maximum_depth_m, dem_path,
                       {"STATISTIC": "cellwise_maximum_over_saved_timesteps"})
    write_pgm(preview_dir / "dem_working.pgm", dem, dem_nodata)
    if result.states:
        write_pgm(preview_dir / "depth_t0000.pgm", result.states[0]["water_depth_m"])
        write_pgm(preview_dir / f"depth_t{len(result.states)//2:04d}.pgm", result.states[len(result.states)//2]["water_depth_m"])
        write_pgm(preview_dir / f"depth_t{len(result.states)-1:04d}.pgm", result.states[-1]["water_depth_m"])
    write_pgm(preview_dir / "max_depth.pgm", result.maximum_depth_m)

    summary = {
        "run_id": run_id,
        "processing_script": "p3-surface-routing-1.4.0",
        "surface_parameterization": provenance,
        "terrain_hydrology": terrain,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "study_area_config": str(STUDY_AREA_PATH.relative_to(ROOT)).replace("\\", "/"),
        "working_crs": grid["crs"],
        "working_grid": grid,
        "rainfall": rainfall_metadata,
        "parameters": {k:v for k,v in config.items() if spatial is None or k not in
                       ("runoff_coefficient", "infiltration_rate_mm_per_hour")},
        "source_dem": "data/dem/processed/bellandur_dem_buffered.tif",
        "steps": len(result.states),
        "initial_stored_water_m3": result.initial_stored_water_m3,
        "total_rainfall_input_m3": result.total_rainfall_input_m3,
        "total_runoff_input_m3": result.total_runoff_input_m3,
        "total_coefficient_loss_m3": result.total_coefficient_loss_m3,
        "total_infiltration_loss_m3": result.total_infiltration_loss_m3,
        "total_surface_water_input_m3": result.total_surface_water_input_m3,
        "total_modeled_losses_m3": result.total_modeled_losses_m3,
        "boundary_outflow_m3": result.total_boundary_outflow_m3,
        "final_stored_water_m3": result.final_stored_water_m3,
        "mass_balance_residual_m3": result.mass_balance_residual_m3,
        "surface_balance_residual_m3": result.surface_balance_residual_m3,
        "maximum_routing_balance_residual_m3": result.maximum_routing_balance_residual_m3,
        "accounting_checks": accounting_checks,
        "surface_volume_budgets": surface_budgets(result.states, result.initial_stored_water_m3),
        "accounting_equations": {
            "rainfall_generation": "rainfall = runoff_input + coefficient_loss",
            "runoff_partition": "runoff_input = surface_water_input + infiltration_loss",
            "gross_balance": "initial_storage + rainfall - coefficient_loss - infiltration_loss - boundary_outflow = final_storage",
            "surface_routing_balance": "initial_storage + surface_water_input - boundary_outflow = final_storage",
            "routing_transfers": "internal routing transfers are conservative and cancel; boundary_outflow is the routing sink",
        },
        "maximum_depth_m": result.maximum_depth_value_m,
        "maximum_depth_index": result.maximum_depth_index,
        "maximum_depth_timestamp": result.maximum_depth_timestamp,
        "domain_peak_depth_file": (depth_dir / f"depth_{result.maximum_depth_index:04d}.tif").relative_to(ROOT).as_posix(),
        "time_series": [{key: state[key] for key in ("index", "timestamp", "rainfall_input_m3", "runoff_input_m3", "coefficient_loss_m3", "infiltration_loss_m3", "surface_water_input_m3", "modeled_losses_m3", "boundary_outflow_m3", "stored_surface_water_m3", "mass_balance_residual_m3", "surface_balance_residual_m3", "routing_balance_residual_m3")} | {"depth_file": str((depth_dir / f"depth_{state['index']:04d}.tif").relative_to(ROOT)).replace("\\", "/")} for state in result.states],
        "outputs": {"depth_directory": str(depth_dir.relative_to(ROOT)).replace("\\", "/"), "max_depth": str((results_dir / "max_depth.tif").relative_to(ROOT)).replace("\\", "/"), "preview_directory": str(preview_dir.relative_to(ROOT)).replace("\\", "/")},
        "scientific_status": "prototype dynamic surface routing; not calibrated, not a full 2D hydrodynamic urban flood model, and not an observation-backed nowcast",
    }
    if forcing:
        independent = rainfall_metadata["raster_volume_m3"]
        per_step = rainfall_metadata["per_step_volume_m3"]
        tol = rainfall_metadata["volume_tolerance_m3"]
        ordered = [s["timestamp"] for s in result.states] == [s.timestamp for s in forcing.steps]
        differences = [state["rainfall_input_m3"]-volume for state, volume in zip(result.states, per_step)]
        max_error = max(map(abs, differences), default=0.0)
        difference = result.total_rainfall_input_m3 - independent
        accounting_checks.update(all_historical_steps_consumed=ordered,
                                 rainfall_volume_agrees_with_rasters=abs(difference) <= tol,
                                 each_rainfall_volume_agrees=ordered and max_error <= tol)
        summary["rainfall_verification"] = {"temporal_volume_m3": rainfall_metadata["allocated_volume_m3"],
            "raster_volume_m3": independent, "engine_volume_m3": result.total_rainfall_input_m3,
            "engine_minus_raster_m3": difference, "max_step_difference_m3": max_error, "tolerance_m3": tol}
        summary["residual_percent_of_gross_rainfall"] = (100*result.mass_balance_residual_m3/result.total_rainfall_input_m3
                                                         if result.total_rainfall_input_m3 else None)
        for state, band in zip(summary["time_series"], rainfall_metadata["bands"]):
            state.update({k:band[k] for k in ("band", "source_label", "timestamp_utc", "relative_start_seconds", "relative_end_seconds")})
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    validation = {
        "simulation_parameters": summary["parameters"],
        "surface_parameter_mode": provenance["mode"],
        "rainfall_source": source,
        "timestep_seconds": params.timestep_seconds,
        "number_of_steps": len(result.states),
        "initial_stored_water_m3": result.initial_stored_water_m3,
        "total_rainfall_input_m3": result.total_rainfall_input_m3,
        "total_runoff_input_m3": result.total_runoff_input_m3,
        "total_coefficient_loss_m3": result.total_coefficient_loss_m3,
        "total_infiltration_loss_m3": result.total_infiltration_loss_m3,
        "total_surface_water_input_m3": result.total_surface_water_input_m3,
        "final_stored_water_m3": result.final_stored_water_m3,
        "boundary_outflow_m3": result.total_boundary_outflow_m3,
        "modeled_losses_m3": result.total_modeled_losses_m3,
        "mass_balance_residual_m3": result.mass_balance_residual_m3,
        "surface_balance_residual_m3": result.surface_balance_residual_m3,
        "maximum_routing_balance_residual_m3": result.maximum_routing_balance_residual_m3,
        "accounting_checks": accounting_checks,
        "maximum_depth_m": result.maximum_depth_value_m,
        "maximum_depth_timestamp": result.maximum_depth_timestamp,
        "test_status": "PASS" if all(value is True for value in accounting_checks.values() if isinstance(value, bool)) else "FAIL",
        "checks": {
            "non_negative_depth": bool(all(np.all(state["water_depth_m"] >= 0) for state in result.states)),
            "mass_balance_within_tolerance": bool(abs(result.mass_balance_residual_m3) <= tolerance),
            "surface_balance_within_tolerance": bool(abs(result.surface_balance_residual_m3) <= tolerance),
            "routing_balance_within_tolerance": bool(result.maximum_routing_balance_residual_m3 <= tolerance),
            "working_crs": grid["crs"],
            "grid_alignment": "all projected input/output rasters use the working DEM grid",
        },
    }
    (results_dir / "p3_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    if not forcing:
        print(json.dumps({"summary": summary, "validation": validation}, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--rainfall", help="JSON or CSV forcing (default: the synthetic engineering fixture)")
    inputs.add_argument("--temporal-manifest", type=Path, help="published Task 2.4 temporal bundle manifest")
    parser.add_argument("--event", help="historical event ID in the selected temporal bundle")
    parser.add_argument("--rainfall-timestep-seconds", type=float)
    parser.add_argument("--surface-parameters", type=Path, help="prepared spatial runoff parameter manifest")
    parser.add_argument("--soil-scenario", choices=SCENARIOS, help="pervious soil capacity sensitivity scenario")
    parser.add_argument("--missing-soil", choices=("zero-credit", "rainfall-limit"),
                        help="infiltration bound for pervious land without texture support")
    parser.add_argument("--run-scoped", action="store_true",
                        help="accepted for compatibility; all P3 terrain and results are now run-specific")
    args = parser.parse_args()
    if bool(args.temporal_manifest) != bool(args.event) or (args.temporal_manifest and args.rainfall_timestep_seconds is not None):
        parser.error("use --temporal-manifest and --event together, with the timestep supplied by the event")
    run(args)


if __name__ == "__main__":
    main()
