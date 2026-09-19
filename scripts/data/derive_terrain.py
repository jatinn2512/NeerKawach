"""Derive terrain-analysis rasters from the prepared buffered Bellandur DEM.

This stage produces static terrain derivatives only. It does not move water,
fill depressions, model runoff, calculate flood depth/extent, or perform
routing. The implementation uses a Horn 3x3 gradient, D8 steepest-descent
flow direction, topological D8 contributing-cell accumulation, and an
unfilled raw-D8 sink classification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "study_area.json"
INPUT_DEM = ROOT / "data" / "dem" / "processed" / "bellandur_dem_buffered.tif"
OUTPUT_DIR = ROOT / "data" / "dem" / "terrain"
METADATA_PATH = ROOT / "data" / "dem" / "metadata" / "terrain_derivatives.json"

SLOPE_PATH = OUTPUT_DIR / "slope.tif"
ASPECT_PATH = OUTPUT_DIR / "aspect.tif"
FLOW_DIRECTION_PATH = OUTPUT_DIR / "flow_direction.tif"
FLOW_ACCUMULATION_PATH = OUTPUT_DIR / "flow_accumulation.tif"
DEPRESSIONS_PATH = OUTPUT_DIR / "depressions.tif"
LOW_POINTS_PATH = OUTPUT_DIR / "low_points.geojson"

SCRIPT_VERSION = "p2-terrain-derivatives-1.0.0"
FLOAT_NODATA = -9999.0
INTEGER_NODATA = -9999
DEPRESSION_NODATA = 255

# ESRI-style D8 encoding: powers of two, clockwise from east. Array rows grow
# southward, so north is -1 row and south is +1 row.
D8_DIRECTIONS = (
    (-1, 0, 64, "N"),
    (-1, 1, 128, "NE"),
    (0, 1, 1, "E"),
    (1, 1, 2, "SE"),
    (1, 0, 4, "S"),
    (1, -1, 8, "SW"),
    (0, -1, 16, "W"),
    (-1, -1, 32, "NW"),
)
D8_BY_CODE = {code: (dr, dc, label) for dr, dc, code, label in D8_DIRECTIONS}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_input(area: dict) -> tuple[np.ndarray, dict, float, float, float]:
    if not INPUT_DEM.exists():
        raise FileNotFoundError(INPUT_DEM)
    with rasterio.open(INPUT_DEM) as dataset:
        if dataset.count != 1:
            raise ValueError("Buffered DEM must contain exactly one band")
        if dataset.crs is None or dataset.crs.to_string() != "EPSG:4326":
            raise ValueError(f"Unexpected DEM CRS: {dataset.crs}")
        if dataset.nodata is None:
            raise ValueError("Buffered DEM has no declared nodata value")
        if dataset.width < 3 or dataset.height < 3:
            raise ValueError("Buffered DEM is too small for a 3x3 terrain kernel")
        bbox = area["bbox"]
        bounds = dataset.bounds
        if not (bounds.left <= bbox["min_lon"] and bounds.right >= bbox["max_lon"] and bounds.bottom <= bbox["min_lat"] and bounds.top >= bbox["max_lat"]):
            raise ValueError("Buffered DEM does not cover canonical study area")
        x_size = abs(dataset.transform.a)
        y_size = abs(dataset.transform.e)
        if not (math.isclose(x_size, y_size, rel_tol=0, abs_tol=1e-12) and x_size > 0):
            raise ValueError("Buffered DEM has an invalid or non-square pixel transform")
        dem = dataset.read(1).astype(np.float64)
        transform = dataset.transform
        nodata = float(dataset.nodata)
        valid = np.isfinite(dem) & (dem != nodata)
        if not np.any(valid):
            raise ValueError("Buffered DEM has no valid elevation cells")
        input_info = {
            "file": str(INPUT_DEM.relative_to(ROOT)).replace("\\", "/"),
            "crs": dataset.crs.to_string(),
            "width": dataset.width,
            "height": dataset.height,
            "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
            "pixel_size_degrees": [x_size, y_size],
            "extent": {"min_lon": bounds.left, "min_lat": bounds.bottom, "max_lon": bounds.right, "max_lat": bounds.top},
            "nodata": nodata,
            "valid_pixel_count": int(valid.sum()),
            "sha256_before": sha256(INPUT_DEM),
        }
    latitude_mid = (bounds.top + bounds.bottom) / 2.0
    meters_per_degree_lat = 111320.0
    meters_per_degree_lon = 111320.0 * math.cos(math.radians(latitude_mid))
    dx_m = x_size * meters_per_degree_lon
    dy_m = y_size * meters_per_degree_lat
    return dem, input_info, dx_m, dy_m, valid


def write_raster(path: Path, values: np.ndarray, profile: dict, dtype: str, nodata: float | int, tags: dict[str, str]) -> None:
    output_profile = profile.copy()
    output_profile.update(
        count=1,
        dtype=dtype,
        nodata=nodata,
        compress="deflate",
        predictor=3 if dtype.startswith("float") else 2,
        BIGTIFF="IF_SAFER",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **output_profile) as dataset:
        dataset.write(values.astype(dtype, copy=False), 1)
        dataset.update_tags(**tags)


def derive_slope_aspect(dem: np.ndarray, valid: np.ndarray, dx_m: float, dy_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows, cols = dem.shape
    slope = np.full((rows, cols), FLOAT_NODATA, dtype=np.float32)
    aspect = np.full((rows, cols), FLOAT_NODATA, dtype=np.float32)
    kernel_valid = valid.copy()
    kernel_valid[0, :] = False
    kernel_valid[-1, :] = False
    kernel_valid[:, 0] = False
    kernel_valid[:, -1] = False
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            shifted = np.zeros_like(valid)
            source_rows = slice(max(0, -dr), min(rows, rows - dr))
            source_cols = slice(max(0, -dc), min(cols, cols - dc))
            target_rows = slice(max(0, dr), min(rows, rows + dr))
            target_cols = slice(max(0, dc), min(cols, cols + dc))
            shifted[target_rows, target_cols] = valid[source_rows, source_cols]
            kernel_valid &= shifted

    z = dem
    dzdx = ((z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:]) - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])) / (8.0 * dx_m)
    dzdy_north = ((z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:]) - (z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:])) / (8.0 * dy_m)
    magnitude = np.hypot(dzdx, dzdy_north)
    slope_inner = np.degrees(np.arctan(magnitude))
    slope[1:-1, 1:-1][kernel_valid[1:-1, 1:-1]] = slope_inner[kernel_valid[1:-1, 1:-1]].astype(np.float32)

    # Aspect is the azimuth of the downslope vector, clockwise from north.
    # Flat cells have no defined aspect and retain FLOAT_NODATA.
    downslope_east = -dzdx
    downslope_north = -dzdy_north
    aspect_inner = (np.degrees(np.arctan2(downslope_east, downslope_north)) + 360.0) % 360.0
    aspect_mask = kernel_valid[1:-1, 1:-1] & (magnitude > 1e-12)
    aspect[1:-1, 1:-1][aspect_mask] = aspect_inner[aspect_mask].astype(np.float32)
    return slope, aspect, kernel_valid


def derive_flow_direction(dem: np.ndarray, valid: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    rows, cols = dem.shape
    direction = np.full((rows, cols), INTEGER_NODATA, dtype=np.int16)
    distances = {(dr, dc): math.hypot(dc * dx_m, dr * dy_m) for dr, dc, _, _ in D8_DIRECTIONS}
    for row, col in zip(*np.where(valid)):
        best_gradient = 0.0
        best_code = 0
        elevation = dem[row, col]
        for dr, dc, code, _ in D8_DIRECTIONS:
            nr, nc = row + dr, col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols or not valid[nr, nc]:
                continue
            drop = elevation - dem[nr, nc]
            gradient = drop / distances[(dr, dc)]
            if gradient > best_gradient:
                best_gradient = gradient
                best_code = code
        direction[row, col] = best_code
    return direction


def derive_flow_accumulation(direction: np.ndarray, valid: np.ndarray) -> np.ndarray:
    rows, cols = direction.shape
    accumulation = np.zeros((rows, cols), dtype=np.float64)
    accumulation[valid] = 1.0
    indegree = np.zeros((rows, cols), dtype=np.int32)
    downstream = np.full((rows, cols, 2), -1, dtype=np.int32)
    for row, col in zip(*np.where(valid)):
        code = int(direction[row, col])
        if code == 0:
            continue
        dr, dc, _ = D8_BY_CODE[code]
        nr, nc = row + dr, col + dc
        if 0 <= nr < rows and 0 <= nc < cols and valid[nr, nc]:
            downstream[row, col] = (nr, nc)
            indegree[nr, nc] += 1

    queue = deque((int(row), int(col)) for row, col in zip(*np.where(valid & (indegree == 0))))
    processed = 0
    while queue:
        row, col = queue.popleft()
        processed += 1
        nr, nc = downstream[row, col]
        if nr < 0:
            continue
        accumulation[nr, nc] += accumulation[row, col]
        indegree[nr, nc] -= 1
        if indegree[nr, nc] == 0:
            queue.append((int(nr), int(nc)))
    if processed != int(valid.sum()):
        raise ValueError("D8 graph did not resolve acyclically; accumulation was not completed")
    output = np.full((rows, cols), FLOAT_NODATA, dtype=np.float32)
    output[valid] = accumulation[valid].astype(np.float32)
    return output


def classify_depressions(dem: np.ndarray, valid: np.ndarray, direction: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    rows, cols = dem.shape
    classes = np.full((rows, cols), DEPRESSION_NODATA, dtype=np.uint8)
    classes[valid] = 0
    features = []
    for row, col in zip(*np.where(valid & (direction == 0))):
        neighbors = []
        for dr, dc, _, _ in D8_DIRECTIONS:
            nr, nc = row + dr, col + dc
            if 0 <= nr < rows and 0 <= nc < cols and valid[nr, nc]:
                neighbors.append(float(dem[nr, nc]))
        is_boundary = len(neighbors) < 8
        has_equal = any(math.isclose(value, float(dem[row, col]), abs_tol=0.0) for value in neighbors)
        if is_boundary:
            class_code, sink_type = 3, "boundary_sink"
        elif has_equal:
            class_code, sink_type = 2, "flat_or_tied_sink"
        else:
            class_code, sink_type = 1, "local_minimum"
        classes[row, col] = class_code
        features.append({"row": int(row), "column": int(col), "elevation_m": float(dem[row, col]), "sink_type": sink_type, "neighbor_count": len(neighbors)})
    return classes, features


def write_low_points(features: list[dict], transform: Affine, bbox: dict) -> None:
    geojson_features = []
    for feature in features:
        # The prepared DEM is AREA_OR_POINT=Point; use the source posting
        # coordinate represented by the affine transform.
        longitude, latitude = transform * (feature["column"], feature["row"])
        geojson_features.append({
            "type": "Feature",
            "id": f"sink-{feature['row']}-{feature['column']}",
            "properties": {key: value for key, value in feature.items() if key not in {"row", "column"}},
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        })
    payload = {
        "type": "FeatureCollection",
        "name": "bellandur_raw_d8_sink_points",
        "bbox": [bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]],
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": geojson_features,
    }
    LOW_POINTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def raster_summary(path: Path, valid_range: tuple[float, float] | None = None) -> dict:
    with rasterio.open(path) as dataset:
        values = dataset.read(1)
        nodata = dataset.nodata
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        if not np.any(valid):
            raise ValueError(f"No valid cells in {path}")
        if valid_range is not None and (float(values[valid].min()) < valid_range[0] or float(values[valid].max()) > valid_range[1]):
            raise ValueError(f"Values outside expected range in {path}")
        return {
            "file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "width": dataset.width,
            "height": dataset.height,
            "transform": [dataset.transform.a, dataset.transform.b, dataset.transform.c, dataset.transform.d, dataset.transform.e, dataset.transform.f],
            "pixel_size_degrees": [abs(dataset.transform.a), abs(dataset.transform.e)],
            "extent": {"min_lon": dataset.bounds.left, "min_lat": dataset.bounds.bottom, "max_lon": dataset.bounds.right, "max_lat": dataset.bounds.top},
            "nodata": nodata,
            "minimum": float(values[valid].min()),
            "maximum": float(values[valid].max()),
            "valid_pixel_count": int(valid.sum()),
            "nodata_pixel_count": int(values.size - valid.sum()),
        }


def validate_alignment(input_info: dict, outputs: list[dict]) -> None:
    expected = input_info["transform"]
    for output in outputs:
        if output["crs"] != input_info["crs"] or output["width"] != input_info["width"] or output["height"] != input_info["height"]:
            raise ValueError(f"Grid shape/CRS mismatch in {output['file']}")
        if not np.allclose(output["transform"], expected, rtol=0, atol=1e-12):
            raise ValueError(f"Grid transform mismatch in {output['file']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    area = load_json(CONFIG_PATH)
    if area.get("crs") != "EPSG:4326":
        raise ValueError("Canonical study area must remain EPSG:4326")
    dem, input_info, dx_m, dy_m, valid = validate_input(area)
    input_hash_after_read = sha256(INPUT_DEM)
    if input_hash_after_read != input_info["sha256_before"]:
        raise ValueError("Input DEM changed during processing")

    with rasterio.open(INPUT_DEM) as dataset:
        profile = dataset.profile.copy()
        transform = dataset.transform

    slope, aspect, derivative_valid = derive_slope_aspect(dem, valid, dx_m, dy_m)
    direction = derive_flow_direction(dem, valid, dx_m, dy_m)
    accumulation = derive_flow_accumulation(direction, valid)
    depression_classes, low_points = classify_depressions(dem, valid, direction)

    tags = {"PROCESSING_SCRIPT": SCRIPT_VERSION, "SOURCE_DEM": str(INPUT_DEM.relative_to(ROOT)).replace("\\", "/")}
    write_raster(SLOPE_PATH, slope, profile, "float32", FLOAT_NODATA, {**tags, "UNITS": "degrees", "METHOD": "Horn 3x3 gradient; geographic pixels converted to local metres"})
    write_raster(ASPECT_PATH, aspect, profile, "float32", FLOAT_NODATA, {**tags, "UNITS": "degrees azimuth", "CONVENTION": "downslope azimuth clockwise from north; flat cells nodata"})
    write_raster(FLOW_DIRECTION_PATH, direction, profile, "int16", INTEGER_NODATA, {**tags, "METHOD": "D8 steepest positive elevation drop per neighbour distance", "ENCODING": "E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128; 0=sink/no positive descent"})
    write_raster(FLOW_ACCUMULATION_PATH, accumulation, profile, "float32", FLOAT_NODATA, {**tags, "METHOD": "topological accumulation over generated D8 graph", "INTERPRETATION": "number of contributing valid DEM cells including the current cell"})
    write_raster(DEPRESSIONS_PATH, depression_classes, profile, "uint8", DEPRESSION_NODATA, {**tags, "METHOD": "unfilled raw-D8 sink classification", "ENCODING": "0=non-sink, 1=local minimum, 2=flat/tied sink, 3=boundary sink"})
    write_low_points(low_points, transform, input_info["extent"])

    summaries = [
        raster_summary(SLOPE_PATH, (0.0, 90.0)),
        raster_summary(ASPECT_PATH, (0.0, 360.0)),
        raster_summary(FLOW_DIRECTION_PATH, (0.0, 128.0)),
        raster_summary(FLOW_ACCUMULATION_PATH, (1.0, float(valid.sum()))),
        raster_summary(DEPRESSIONS_PATH, (0.0, 3.0)),
    ]
    validate_alignment(input_info, summaries)
    if len(low_points) != int(np.count_nonzero(depression_classes > 0)):
        raise ValueError("Low-point vector count does not match depression raster")

    report = {
        "processing_script": SCRIPT_VERSION,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "source_dem": input_info,
        "crs": input_info["crs"],
        "pixel_size_degrees": input_info["pixel_size_degrees"],
        "pixel_size_metres_at_dem_midlatitude": {"east_west": dx_m, "north_south": dy_m},
        "extent": input_info["extent"],
        "nodata_handling": {"input": input_info["nodata"], "float_outputs": FLOAT_NODATA, "integer_outputs": INTEGER_NODATA, "depression_output": DEPRESSION_NODATA},
        "algorithms": {
            "slope": "Horn 3x3 finite-difference gradient; degrees",
            "aspect": "downslope azimuth from the negative elevation gradient; clockwise from north; degrees 0-360; flat cells nodata",
            "flow_direction": "D8 steepest positive drop divided by neighbour distance",
            "flow_accumulation": "topological D8 contributing-cell count including the focal cell",
            "depressions": "unfilled raw-D8 sinks; local minima, flat/tied sinks and boundary sinks classified separately",
        },
        "outputs": {"slope": summaries[0], "aspect": summaries[1], "flow_direction": summaries[2], "flow_accumulation": summaries[3], "depressions": summaries[4], "low_points": {"file": str(LOW_POINTS_PATH.relative_to(ROOT)).replace("\\", "/"), "feature_count": len(low_points), "crs": "EPSG:4326"}},
        "validation": {
            "source_dem_unchanged": input_hash_after_read == input_info["sha256_before"],
            "crs_consistent": all(item["crs"] == input_info["crs"] for item in summaries),
            "grid_alignment_consistent": True,
            "resolution_preserved": all(item["pixel_size_degrees"] == input_info["pixel_size_degrees"] for item in summaries),
            "flow_direction_codes_valid": bool(np.all(np.isin(direction[valid], [0, 1, 2, 4, 8, 16, 32, 64, 128]))),
            "no_unexpected_empty_derivative_cells": bool(all(item["nodata_pixel_count"] == 0 for item in summaries[2:])),
            "slope_kernel_nodata_cells": int(np.count_nonzero(~derivative_valid)),
        },
        "limitations": [
            "Derivatives are static terrain indicators, not a flood simulation or hydraulic model.",
            "The DEM remains in geographic CRS; slope distances use local metre approximations at the raster mid-latitude.",
            "Raw D8 sinks are not filled and cannot by themselves distinguish natural depressions from DEM artefacts or urban drainage controls.",
            "Boundary cells have incomplete neighbourhoods and are classified separately where relevant.",
        ],
    }
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
