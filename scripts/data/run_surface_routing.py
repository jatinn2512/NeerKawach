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

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine, rowcol
from rasterio.warp import calculate_default_transform, reproject, transform

from surface_routing_core import RainfallStep, RoutingParameters, SimulationResult, simulate


ROOT = Path(__file__).resolve().parents[2]
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"
ROUTING_CONFIG_PATH = ROOT / "config" / "surface_routing.json"
P2_INPUTS = {
    "dem": ROOT / "data" / "dem" / "processed" / "bellandur_dem_buffered.tif",
    "slope": ROOT / "data" / "dem" / "terrain" / "slope.tif",
    "aspect": ROOT / "data" / "dem" / "terrain" / "aspect.tif",
    "flow_direction": ROOT / "data" / "dem" / "terrain" / "flow_direction.tif",
    "flow_accumulation": ROOT / "data" / "dem" / "terrain" / "flow_accumulation.tif",
    "depressions": ROOT / "data" / "dem" / "terrain" / "depressions.tif",
}
WORKING_DIR = ROOT / "data" / "surface_routing" / "input"
RESULTS_DIR = ROOT / "data" / "surface_routing" / "results"
DEPTH_DIR = RESULTS_DIR / "depth"
PREVIEW_DIR = RESULTS_DIR / "preview"
WORKING_CRS = "EPSG:32643"
WORKING_RESOLUTION_M = 30.0


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_projected_inputs() -> dict:
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

    resampling = {"dem": Resampling.bilinear, "slope": Resampling.nearest, "aspect": Resampling.nearest, "flow_direction": Resampling.nearest, "flow_accumulation": Resampling.nearest, "depressions": Resampling.nearest}
    projected = {}
    for name, path in P2_INPUTS.items():
        with rasterio.open(path) as source:
            source_data = source.read(1)
            source_nodata = source.nodata
            dtype = source.dtypes[0]
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
            output_path = WORKING_DIR / f"{name}_working.tif"
            profile = source.profile.copy()
            profile.update(driver="GTiff", height=height, width=width, count=1, crs=WORKING_CRS, transform=dst_transform, dtype=dtype, nodata=destination_nodata, compress="deflate", predictor=3 if dtype.startswith("float") else 2, BIGTIFF="IF_SAFER")
            WORKING_DIR.mkdir(parents=True, exist_ok=True)
            with rasterio.open(output_path, "w", **profile) as target:
                target.write(destination, 1)
                target.update_tags(SOURCE_FILE=str(path.relative_to(ROOT)).replace("\\", "/"), WORKING_CRS=WORKING_CRS, RESAMPLING=resampling[name].name, PROCESSING="P3 projected working input")
            projected[name] = {"file": str(output_path.relative_to(ROOT)).replace("\\", "/"), "dtype": dtype, "nodata": destination_nodata}

    with rasterio.open(WORKING_DIR / "dem_working.tif") as dataset:
        grid = {
            "crs": WORKING_CRS,
            "width": dataset.width,
            "height": dataset.height,
            "transform": list(dataset.transform),
            "pixel_size_m": [abs(dataset.transform.a), abs(dataset.transform.e)],
            "extent": {"min_x": dataset.bounds.left, "min_y": dataset.bounds.bottom, "max_x": dataset.bounds.right, "max_y": dataset.bounds.top},
            "cell_area_m2": abs(dataset.transform.a * dataset.transform.e),
        }
    (WORKING_DIR / "working_grid.json").write_text(json.dumps({"source_grid": source_grid, "working_grid": grid, "working_crs_reason": "UTM zone 43N is the appropriate local projected CRS for Bengaluru longitude ~77.65E and provides metre-based distance/area calculations without changing the canonical EPSG:4326 study-area definition.", "outputs": projected}, indent=2) + "\n", encoding="utf-8")
    return {"area": area, "grid": grid, "projected": projected}


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
    profile.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, compress="deflate", predictor=3, BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **profile) as dataset:
        output = depth.astype(np.float32, copy=True)
        output[output < 0] = 0
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
    prepared = prepare_projected_inputs()
    grid = prepared["grid"]
    with rasterio.open(WORKING_DIR / "dem_working.tif") as dem_dataset:
        dem = dem_dataset.read(1).astype(np.float64)
        dem_nodata = dem_dataset.nodata
        template_profile = dem_dataset.profile.copy()
    valid = np.isfinite(dem) & (dem != dem_nodata)
    with rasterio.open(WORKING_DIR / "flow_direction_working.tif") as direction_dataset:
        direction = direction_dataset.read(1)
        if direction.shape != dem.shape:
            raise ValueError("Projected flow direction is not aligned with projected DEM")
    source, forcing_timestep, rainfall_steps, rainfall_metadata = load_rainfall(Path(args.rainfall), dem.shape, grid, args.rainfall_timestep_seconds)
    config = load_json(ROUTING_CONFIG_PATH)
    params = RoutingParameters(**{key: config[key] for key in RoutingParameters.__dataclass_fields__})
    if abs(params.timestep_seconds - forcing_timestep) > 1e-9:
        raise ValueError("Rainfall timestep and routing timestep do not match")
    result: SimulationResult = simulate(dem, valid, rainfall_steps, grid["cell_area_m2"], params, direction, grid["pixel_size_m"][0], grid["pixel_size_m"][1])
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

    DEPTH_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for state in result.states:
        write_depth_raster(DEPTH_DIR / f"depth_{state['index']:04d}.tif", state["water_depth_m"], WORKING_DIR / "dem_working.tif", {"TIMESTEP_INDEX": str(state["index"]), "TIMESTAMP": state["timestamp"]})
    write_depth_raster(RESULTS_DIR / "max_depth.tif", result.maximum_depth_m, WORKING_DIR / "dem_working.tif", {"MAXIMUM_DEPTH_TIMESTAMP": result.maximum_depth_timestamp or "", "MAXIMUM_DEPTH_INDEX": str(result.maximum_depth_index if result.maximum_depth_index is not None else "")})
    write_pgm(PREVIEW_DIR / "dem_working.pgm", dem, dem_nodata)
    if result.states:
        write_pgm(PREVIEW_DIR / "depth_t0000.pgm", result.states[0]["water_depth_m"])
        write_pgm(PREVIEW_DIR / f"depth_t{len(result.states)//2:04d}.pgm", result.states[len(result.states)//2]["water_depth_m"])
        write_pgm(PREVIEW_DIR / f"depth_t{len(result.states)-1:04d}.pgm", result.states[-1]["water_depth_m"])
    write_pgm(PREVIEW_DIR / "max_depth.pgm", result.maximum_depth_m)

    summary = {
        "processing_script": "p3-surface-routing-1.0.0",
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "study_area_config": str(STUDY_AREA_PATH.relative_to(ROOT)).replace("\\", "/"),
        "working_crs": grid["crs"],
        "working_grid": grid,
        "rainfall": rainfall_metadata,
        "parameters": config,
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
        "time_series": [{key: state[key] for key in ("index", "timestamp", "rainfall_input_m3", "runoff_input_m3", "coefficient_loss_m3", "infiltration_loss_m3", "surface_water_input_m3", "modeled_losses_m3", "boundary_outflow_m3", "stored_surface_water_m3", "mass_balance_residual_m3", "surface_balance_residual_m3", "routing_balance_residual_m3")} | {"depth_file": str((DEPTH_DIR / f"depth_{state['index']:04d}.tif").relative_to(ROOT)).replace("\\", "/")} for state in result.states],
        "outputs": {"depth_directory": str(DEPTH_DIR.relative_to(ROOT)).replace("\\", "/"), "max_depth": str((RESULTS_DIR / "max_depth.tif").relative_to(ROOT)).replace("\\", "/"), "preview_directory": str(PREVIEW_DIR.relative_to(ROOT)).replace("\\", "/")},
        "scientific_status": "prototype dynamic surface routing; not calibrated, not a full 2D hydrodynamic urban flood model, and not an observation-backed nowcast",
    }
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    validation = {
        "simulation_parameters": config,
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
    (RESULTS_DIR / "p3_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "validation": validation}, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rainfall", default=str(ROOT / "data" / "surface_routing" / "tests" / "synthetic_rainfall.json"))
    parser.add_argument("--rainfall-timestep-seconds", type=float)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
