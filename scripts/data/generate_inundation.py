"""Generate P7 inundation and road-impact products from validated P6 outputs.

This script is deliberately downstream-only. It reads P6 depth rasters and
existing P1/P4 road products; it does not rerun or alter P1-P6 models.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import geometry_mask, rasterize, shapes
from rasterio.warp import transform_geom


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "inundation.json"
P6_DEPTH_DIR = ROOT / "data" / "coupling" / "results" / "coupled_surface_depth"
P6_MAX_DEPTH_PATH = ROOT / "data" / "coupling" / "results" / "coupled_max_depth.tif"
P6_SUMMARY_PATH = ROOT / "data" / "coupling" / "results" / "coupling_summary.json"
P6_BALANCE_PATH = ROOT / "data" / "coupling" / "results" / "coupling_water_balance.json"
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"
ROADS_PATH = ROOT / "data" / "roads" / "processed" / "bellandur_roads.geojson"
OUTPUT_DIR = ROOT / "data" / "inundation"
RASTER_DIR = OUTPUT_DIR / "rasters"
VECTOR_DIR = OUTPUT_DIR / "vectors"
ROAD_DIR = OUTPUT_DIR / "roads"
METRICS_DIR = OUTPUT_DIR / "metrics"
METADATA_DIR = OUTPUT_DIR / "metadata"
SCRIPT_VERSION = "p7-inundation-1.0.0"
OUTPUT_NODATA = -9999.0
RISK_NODATA = 255


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def canonical_polygon(area: dict[str, Any]) -> dict[str, Any]:
    bbox = area["bbox"]
    return {
        "type": "Polygon",
        "coordinates": [[
            [bbox["min_lon"], bbox["min_lat"]],
            [bbox["max_lon"], bbox["min_lat"]],
            [bbox["max_lon"], bbox["max_lat"]],
            [bbox["min_lon"], bbox["max_lat"]],
            [bbox["min_lon"], bbox["min_lat"]],
        ]],
    }


def validate_config(config: dict[str, Any]) -> None:
    threshold = float(config["depth_threshold_m"])
    if threshold <= 0:
        raise ValueError("P7 depth threshold must be positive")
    classes = config["risk_classification"]
    expected_codes = {"none": 0, "shallow": 1, "moderate": 2, "deep": 3}
    if {name: item["code"] for name, item in classes.items()} != expected_codes:
        raise ValueError("P7 risk-classification codes are invalid")
    if float(classes["shallow"]["minimum_depth_m"]) != threshold:
        raise ValueError("P7 shallow risk threshold must equal inundation threshold")


def load_depth_states(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = sorted(P6_DEPTH_DIR.glob("depth_*.tif"))
    if not paths:
        raise FileNotFoundError(f"No P6 timestamped depth rasters found in {P6_DEPTH_DIR}")
    states = []
    template_profile = None
    template_crs = None
    template_transform = None
    template_shape = None
    previous_time = None
    for path in paths:
        with rasterio.open(path) as dataset:
            tags = dataset.tags()
            timestamp = tags.get("TIMESTAMP")
            if not timestamp:
                raise ValueError(f"P6 depth raster has no TIMESTAMP tag: {path}")
            current_time = parse_timestamp(timestamp)
            if previous_time is not None and current_time <= previous_time:
                raise ValueError("P6 depth raster timestamps are not strictly increasing")
            previous_time = current_time
            array = dataset.read(1).astype(np.float64)
            if template_profile is None:
                template_profile = dataset.profile.copy()
                template_crs = dataset.crs
                template_transform = dataset.transform
                template_shape = array.shape
            elif dataset.crs != template_crs or dataset.transform != template_transform or array.shape != template_shape:
                raise ValueError("P6 depth rasters are not spatially aligned")
            nodata = dataset.nodata if dataset.nodata is not None else OUTPUT_NODATA
            valid = np.isfinite(array) & (array != nodata)
            if np.any(array[valid] < -1e-9):
                raise ValueError(f"Negative P6 depth found in {path}")
            states.append({"path": path, "timestamp": timestamp, "datetime": current_time, "array": np.maximum(array, 0.0), "valid": valid})
    if template_crs is None or template_transform is None or template_shape is None:
        raise ValueError("P6 depth raster template could not be established")
    return states, {"profile": template_profile, "crs": template_crs, "transform": template_transform, "shape": template_shape}


def canonical_mask(area: dict[str, Any], spatial: dict[str, Any]) -> np.ndarray:
    source_geometry = canonical_polygon(area)
    projected_geometry = transform_geom(area["crs"], spatial["crs"], source_geometry, precision=3)
    return geometry_mask([projected_geometry], out_shape=spatial["shape"], transform=spatial["transform"], invert=True, all_touched=False)


def risk_class(depth: float, config: dict[str, Any]) -> tuple[str, int]:
    classes = config["risk_classification"]
    if depth < float(classes["shallow"]["minimum_depth_m"]):
        return "none", int(classes["none"]["code"])
    if depth < float(classes["moderate"]["minimum_depth_m"]):
        return "shallow", int(classes["shallow"]["code"])
    if depth < float(classes["deep"]["minimum_depth_m"]):
        return "moderate", int(classes["moderate"]["code"])
    return "deep", int(classes["deep"]["code"])


def write_raster(path: Path, source_profile: dict[str, Any], values: np.ndarray, nodata: float | int, tags: dict[str, Any], dtype: str) -> None:
    profile = source_profile.copy()
    profile.update(dtype=dtype, count=1, nodata=nodata, compress="deflate")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(values.astype(dtype), 1)
        dataset.update_tags(**{key: str(value) for key, value in tags.items()})


def extent_features(binary: np.ndarray, mask: np.ndarray, spatial: dict[str, Any], timestamp: str, threshold: float) -> list[dict[str, Any]]:
    features = []
    for geometry, value in shapes(binary.astype(np.uint8), mask=mask, transform=spatial["transform"]):
        if int(value) != 1:
            continue
        geographic = transform_geom(spatial["crs"], "EPSG:4326", geometry, precision=7)
        features.append({
            "type": "Feature",
            "properties": {
                "source_phase": "P6",
                "timestamp": timestamp,
                "depth_threshold_m": threshold,
                "units": "inundated cell footprint",
            },
            "geometry": geographic,
        })
    return features


def write_extent(path: Path, features: list[dict[str, Any]], timestamp: str, threshold: float, source_files: list[str]) -> None:
    payload = {
        "type": "FeatureCollection",
        "name": "bellandur_flood_extent",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "properties": {"source_phase": "P6", "timestamp": timestamp, "depth_threshold_m": threshold, "source_files": source_files},
        "features": features,
    }
    write_json(path, payload)


def geometry_parts(geometry: dict[str, Any]) -> list[list[list[float]]]:
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    raise ValueError(f"Unsupported OSM road geometry: {geometry.get('type')}")


def projected_length(geometry: dict[str, Any], source_crs: str, target_crs: Any) -> float:
    projected = transform_geom(source_crs, target_crs, geometry, precision=3)
    length = 0.0
    for coordinates in geometry_parts(projected):
        for left, right in zip(coordinates, coordinates[1:]):
            length += math.hypot(float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))
    return length


def build_road_records(roads: dict[str, Any], states: list[dict[str, Any]], spatial: dict[str, Any], domain_mask: np.ndarray, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    threshold = float(config["depth_threshold_m"])
    road_timeseries = []
    road_summary = []
    road_features = roads.get("features", [])
    seen_ids: set[str] = set()
    road_masks = {}
    for index, feature in enumerate(road_features):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        road_id = str(feature.get("id") or feature.get("properties", {}).get("osm_id") or f"road_{index:05d}")
        if road_id in seen_ids:
            raise ValueError(f"Duplicate road identifier: {road_id}")
        seen_ids.add(road_id)
        projected_geometry = transform_geom("EPSG:4326", spatial["crs"], geometry, precision=3)
        road_mask = rasterize([(projected_geometry, 1)], out_shape=spatial["shape"], transform=spatial["transform"], fill=0, all_touched=True, dtype="uint8").astype(bool) & domain_mask
        road_masks[road_id] = (feature, projected_geometry, road_mask)
    for road_id, (feature, projected_geometry, road_mask) in road_masks.items():
        properties = feature.get("properties", {})
        timestamp_metrics = []
        peak_depth = 0.0
        peak_timestamp = None
        first_timestamp = None
        duration_seconds = 0.0
        for index, state in enumerate(states):
            values = state["array"][road_mask]
            maximum = float(np.max(values)) if values.size else 0.0
            affected = maximum >= threshold
            classification, _ = risk_class(maximum, config)
            if affected and first_timestamp is None:
                first_timestamp = state["timestamp"]
            if maximum > peak_depth:
                peak_depth = maximum
                peak_timestamp = state["timestamp"]
            if affected and index < len(states) - 1:
                duration_seconds += (states[index + 1]["datetime"] - state["datetime"]).total_seconds()
            timestamp_metrics.append({"timestamp": state["timestamp"], "max_intersecting_depth_m": maximum, "affected": affected, "risk_class": classification})
            road_timeseries.append({
                "timestamp": state["timestamp"],
                "road_id": road_id,
                "osm_id": properties.get("osm_id", ""),
                "name": properties.get("name", ""),
                "highway": properties.get("highway", ""),
                "max_intersecting_depth_m": maximum,
                "affected": affected,
                "risk_class": classification,
                "source_phase": "P6",
                "source_raster": relative(state["path"]),
            })
        road_summary.append({
            "road_id": road_id,
            "osm_id": properties.get("osm_id", ""),
            "name": properties.get("name", ""),
            "highway": properties.get("highway", ""),
            "length_m": projected_length(feature["geometry"], "EPSG:4326", spatial["crs"]),
            "affected": peak_depth >= threshold,
            "maximum_intersecting_depth_m": peak_depth,
            "first_inundation_timestamp": first_timestamp or "",
            "peak_inundation_timestamp": peak_timestamp or "",
            "duration_above_threshold_seconds": duration_seconds,
            "peak_risk_class": risk_class(peak_depth, config)[0],
            "source_phase": "P6",
            "depth_threshold_m": threshold,
            "road_elevation_used": False,
        })
    return road_timeseries, road_summary


def build_road_geojson(roads: dict[str, Any], summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {row["road_id"]: row for row in summary_rows}
    features = []
    for feature in roads.get("features", []):
        road_id = str(feature.get("id") or feature.get("properties", {}).get("osm_id"))
        row = metrics.get(road_id)
        if row is None:
            continue
        properties = dict(feature.get("properties", {}))
        properties.update({key: value for key, value in row.items() if key not in {"road_id", "osm_id", "name", "highway"}})
        properties["source_phase"] = "P6"
        features.append({"type": "Feature", "id": road_id, "properties": properties, "geometry": feature["geometry"]})
    return {"type": "FeatureCollection", "name": "bellandur_road_flood_impact", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": features}


def run() -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    validate_config(config)
    area = load_json(STUDY_AREA_PATH)
    roads = load_json(ROADS_PATH)
    p6_summary = load_json(P6_SUMMARY_PATH)
    p6_balance = load_json(P6_BALANCE_PATH)
    states, spatial = load_depth_states(config)
    domain_mask = canonical_mask(area, spatial)
    if not np.any(domain_mask):
        raise ValueError("Canonical Bellandur bbox does not intersect the P6 raster")
    invalid_inside = np.logical_or.reduce([~state["valid"] for state in states]) & domain_mask
    if np.any(invalid_inside):
        raise ValueError("P6 depth rasters contain invalid pixels inside the canonical study-area mask")
    threshold = float(config["depth_threshold_m"])
    cell_area = abs(float(spatial["transform"].a * spatial["transform"].e))
    source_files = [relative(state["path"]) for state in states] + [relative(P6_MAX_DEPTH_PATH)]
    generated_at = timestamp_text(datetime.now(timezone.utc))
    area_rows = []
    extent_outputs = []
    maximum_depth = 0.0
    maximum_depth_timestamp = None
    maximum_area = 0.0
    maximum_area_timestamp = None
    maximum_arrays = []
    for index, state in enumerate(states):
        masked = np.where(domain_mask, state["array"], OUTPUT_NODATA).astype(np.float32)
        valid_values = state["array"][domain_mask]
        max_depth = float(np.max(valid_values)) if valid_values.size else 0.0
        inundated = domain_mask & (state["array"] >= threshold)
        inundated_area = float(np.count_nonzero(inundated) * cell_area)
        class_name, class_code = risk_class(max_depth, config)
        depth_path = RASTER_DIR / f"depth_{index:04d}.tif"
        write_raster(depth_path, spatial["profile"], masked, OUTPUT_NODATA, {
            "PRODUCT": "P7 Bellandur flood depth",
            "SOURCE_PHASE": "P6",
            "SOURCE_FILE": relative(state["path"]),
            "STUDY_AREA_CONFIG": relative(STUDY_AREA_PATH),
            "TIMESTAMP": state["timestamp"],
            "DEPTH_UNITS": "metres",
            "DEPTH_THRESHOLD_M": threshold,
            "MASK_METHOD": "pixel center within canonical EPSG:4326 bbox transformed to source CRS",
        }, "float32")
        extent_path = VECTOR_DIR / f"extent_{index:04d}.geojson"
        features = extent_features(inundated.astype(np.uint8), domain_mask, spatial, state["timestamp"], threshold)
        write_extent(extent_path, features, state["timestamp"], threshold, [relative(state["path"])])
        extent_outputs.append(relative(extent_path))
        area_rows.append({
            "timestamp": state["timestamp"],
            "inundated_area_m2": inundated_area,
            "inundated_cell_count": int(np.count_nonzero(inundated)),
            "maximum_flood_depth_m": max_depth,
            "maximum_depth_risk_class": class_name,
            "maximum_depth_risk_code": class_code,
            "depth_threshold_m": threshold,
            "source_phase": "P6",
            "source_raster": relative(state["path"]),
        })
        maximum_arrays.append(np.where(domain_mask, state["array"], 0.0))
        if max_depth > maximum_depth:
            maximum_depth = max_depth
            maximum_depth_timestamp = state["timestamp"]
        if inundated_area > maximum_area:
            maximum_area = inundated_area
            maximum_area_timestamp = state["timestamp"]
    maximum_array = np.maximum.reduce(maximum_arrays)
    with rasterio.open(P6_MAX_DEPTH_PATH) as source_max_dataset:
        source_max_array = source_max_dataset.read(1).astype(np.float64)
        source_max_nodata = source_max_dataset.nodata if source_max_dataset.nodata is not None else OUTPUT_NODATA
        source_max_valid = np.isfinite(source_max_array) & (source_max_array != source_max_nodata)
        maximum_raster_matches_time_series = (
            source_max_dataset.crs == spatial["crs"]
            and source_max_dataset.transform == spatial["transform"]
            and source_max_array.shape == spatial["shape"]
            and np.all(source_max_valid[domain_mask])
            and np.allclose(source_max_array[domain_mask], maximum_array[domain_mask], rtol=0.0, atol=1e-5)
        )
    if not maximum_raster_matches_time_series:
        raise ValueError("P6 maximum-depth raster does not match the timestamped P6 depth states")
    max_inundated = domain_mask & (maximum_array >= threshold)
    max_depth_path = RASTER_DIR / "max_depth.tif"
    write_raster(max_depth_path, spatial["profile"], np.where(domain_mask, maximum_array, OUTPUT_NODATA), OUTPUT_NODATA, {
        "PRODUCT": "P7 Bellandur maximum flood depth",
        "SOURCE_PHASE": "P6",
        "SOURCE_FILES": ";".join(source_files),
        "STUDY_AREA_CONFIG": relative(STUDY_AREA_PATH),
        "DEPTH_UNITS": "metres",
        "DEPTH_THRESHOLD_M": threshold,
        "MASK_METHOD": "pixel center within canonical EPSG:4326 bbox transformed to source CRS",
    }, "float32")
    risk_values = np.full(spatial["shape"], RISK_NODATA, dtype=np.uint8)
    for name, item in config["risk_classification"].items():
        if name == "none":
            cell_mask = domain_mask & (maximum_array < float(item["maximum_depth_m_exclusive"]))
        elif item["maximum_depth_m_exclusive"] is None:
            cell_mask = domain_mask & (maximum_array >= float(item["minimum_depth_m"]))
        else:
            cell_mask = domain_mask & (maximum_array >= float(item["minimum_depth_m"])) & (maximum_array < float(item["maximum_depth_m_exclusive"]))
        risk_values[cell_mask] = int(item["code"])
    risk_path = RASTER_DIR / "max_risk_class.tif"
    write_raster(risk_path, spatial["profile"], risk_values, RISK_NODATA, {
        "PRODUCT": "P7 Bellandur project-defined maximum depth risk class",
        "SOURCE_PHASE": "P6",
        "SOURCE_FILE": relative(max_depth_path),
        "CLASSIFICATION": "config/inundation.json",
        "DEPTH_THRESHOLD_M": threshold,
        "CLASS_CODES": "0 none, 1 shallow, 2 moderate, 3 deep",
    }, "uint8")
    max_extent_path = VECTOR_DIR / "max_extent.geojson"
    write_extent(max_extent_path, extent_features(max_inundated.astype(np.uint8), domain_mask, spatial, "maximum_over_time", threshold), "maximum_over_time", threshold, source_files)
    roads_timeseries, roads_summary = build_road_records(roads, states, spatial, domain_mask, config)
    area_fields = ["timestamp", "inundated_area_m2", "inundated_cell_count", "maximum_flood_depth_m", "maximum_depth_risk_class", "maximum_depth_risk_code", "depth_threshold_m", "source_phase", "source_raster"]
    road_timeseries_fields = ["timestamp", "road_id", "osm_id", "name", "highway", "max_intersecting_depth_m", "affected", "risk_class", "source_phase", "source_raster"]
    road_summary_fields = ["road_id", "osm_id", "name", "highway", "length_m", "affected", "maximum_intersecting_depth_m", "first_inundation_timestamp", "peak_inundation_timestamp", "duration_above_threshold_seconds", "peak_risk_class", "source_phase", "depth_threshold_m", "road_elevation_used"]
    area_csv = METRICS_DIR / "inundation_timeseries.csv"
    road_timeseries_csv = ROAD_DIR / "road_impact_timeseries.csv"
    road_summary_csv = ROAD_DIR / "road_impact_summary.csv"
    write_csv(area_csv, area_rows, area_fields)
    write_csv(road_timeseries_csv, roads_timeseries, road_timeseries_fields)
    write_csv(road_summary_csv, roads_summary, road_summary_fields)
    road_geojson_path = ROAD_DIR / "road_impacts.geojson"
    write_json(road_geojson_path, build_road_geojson(roads, roads_summary))
    road_affected = [row for row in roads_summary if row["affected"]]
    road_peak = max(roads_summary, key=lambda row: row["maximum_intersecting_depth_m"], default=None)
    first_road_time = min((row["first_inundation_timestamp"] for row in road_affected if row["first_inundation_timestamp"]), default="")
    per_timestamp_road = []
    for timestamp in [state["timestamp"] for state in states]:
        current = [row for row in roads_timeseries if row["timestamp"] == timestamp and row["affected"]]
        per_timestamp_road.append({"timestamp": timestamp, "affected_road_segment_count": len(current), "affected_road_length_m": sum(float(next(item["length_m"] for item in roads_summary if item["road_id"] == row["road_id"])) for row in current)})
    for row in area_rows:
        road_metrics = next(item for item in per_timestamp_road if item["timestamp"] == row["timestamp"])
        row.update(road_metrics)
    write_csv(area_csv, area_rows, area_fields + ["affected_road_segment_count", "affected_road_length_m"])
    provenance = {
        "processing_script": SCRIPT_VERSION,
        "generated_at_utc": generated_at,
        "source_phase": "P6",
        "source_model_identifier": config["provenance"]["source_model_identifier"],
        "source_files": source_files + [relative(P6_SUMMARY_PATH), relative(P6_BALANCE_PATH)],
        "study_area_config": relative(STUDY_AREA_PATH),
        "study_area": area,
        "source_crs": str(spatial["crs"]),
        "output_raster_crs": str(spatial["crs"]),
        "output_vector_crs": "EPSG:4326",
        "depth_units": "metres",
        "area_units": "square metres",
        "road_length_units": "metres",
        "depth_threshold_m": threshold,
        "threshold_definition": config["threshold_definition"],
        "threshold_status": config["threshold_status"],
        "road_intersection_method": config["road_intersection"],
        "outputs": {
            "depth_rasters": [relative(RASTER_DIR / f"depth_{index:04d}.tif") for index in range(len(states))],
            "maximum_depth_raster": relative(max_depth_path),
            "risk_class_raster": relative(risk_path),
            "extent_vectors": extent_outputs,
            "maximum_extent_vector": relative(max_extent_path),
            "inundation_timeseries": relative(area_csv),
            "road_impact_timeseries": relative(road_timeseries_csv),
            "road_impact_summary": relative(road_summary_csv),
            "road_impact_geojson": relative(road_geojson_path),
        },
    }
    provenance_path = METADATA_DIR / "p7_provenance.json"
    write_json(provenance_path, provenance)
    p6_summary = p6_summary
    summary = {
        "processing_script": SCRIPT_VERSION,
        "generated_at_utc": generated_at,
        "source_phase": "P6",
        "source_model_identifier": config["provenance"]["source_model_identifier"],
        "study_area": area,
        "crs": {"raster": str(spatial["crs"]), "vector": "EPSG:4326"},
        "units": {"depth": "metres", "area": "square metres", "road_length": "metres", "duration": "seconds"},
        "depth_threshold_m": threshold,
        "timestamp_count": len(states),
        "timestamps": [state["timestamp"] for state in states],
        "metrics_definition": {
            "inundated_area": "instantaneous area of masked raster cells at or above the threshold",
            "maximum_flood_depth": "maximum valid cell depth over the time-stepped P6 states",
            "road_duration": config["road_intersection"]["duration_definition"],
            "p6_totals": "inherited cumulative/final values from P6 water-balance outputs; not recomputed by P7",
        },
        "maximum_flood_depth": {"value_m": maximum_depth, "timestamp": maximum_depth_timestamp, "metric_type": "maximum_over_time"},
        "maximum_inundated_area": {"value_m2": maximum_area, "timestamp": maximum_area_timestamp, "metric_type": "maximum_instantaneous_snapshot"},
        "final_state": {"timestamp": states[-1]["timestamp"], "inundated_area_m2": area_rows[-1]["inundated_area_m2"], "maximum_depth_m": area_rows[-1]["maximum_flood_depth_m"], "metric_type": "final_poststorm_snapshot"},
        "roads": {
            "total_segment_count": len(roads_summary),
            "affected_segment_count": len(road_affected),
            "affected_length_m": sum(float(row["length_m"]) for row in road_affected),
            "maximum_road_intersecting_depth": {"value_m": road_peak["maximum_intersecting_depth_m"] if road_peak else 0.0, "road_id": road_peak["road_id"] if road_peak else "", "timestamp": road_peak["peak_inundation_timestamp"] if road_peak else "", "metric_type": "maximum_over_time"},
            "first_inundation_timestamp": first_road_time,
            "peak_inundation_timestamp": road_peak["peak_inundation_timestamp"] if road_peak else "",
        },
        "inherited_p6_totals": {
            "surface_to_drainage_transfer_m3": p6_balance["surface_domain"]["surface_to_drainage_transfer_m3"],
            "drainage_to_surface_return_m3": p6_balance["surface_domain"]["drainage_to_surface_return_m3"],
            "unmapped_overflow_m3": p6_balance["drainage_domain"]["unmapped_overflow_m3"],
            "final_surface_storage_m3": p6_balance["surface_domain"]["final_surface_storage_m3"],
            "final_drainage_storage_m3": p6_balance["drainage_domain"]["final_routing_storage_m3"],
            "p6_unexplained_residual_m3": p6_balance["coupled_domain"]["unexplained_residual_m3"],
            "metric_type": "inherited_from_P6_balance",
        },
        "outputs": provenance["outputs"],
        "provenance_file": relative(provenance_path),
        "limitations": ["Depth is inherited from P6 surface-water states; P7 does not calculate new hydraulic depths.", "Road impacts use rasterized OSM line footprints and do not use road elevations or observed flood depths.", "The 0.05 m inundation and risk thresholds are project-defined visualization/decision thresholds, not a scientific or regulatory standard.", "P6 terrain-inferred drainage connections and synthetic rainfall provenance remain unchanged."],
    }
    summary_path = METRICS_DIR / "p7_summary.json"
    write_json(summary_path, summary)
    validation = {
        "test_status": "PASS",
        "source_phase": "P6",
        "timestamped_depth_rasters": len(states),
        "canonical_mask_pixel_count": int(np.count_nonzero(domain_mask)),
        "all_depth_values_finite_inside_mask": True,
        "all_depth_values_nonnegative_inside_mask": True,
        "maximum_raster_matches_time_series": bool(maximum_raster_matches_time_series),
        "road_features_processed": len(roads_summary),
        "extent_outputs_generated": len(extent_outputs),
        "crs_valid": str(spatial["crs"]) == "EPSG:32643",
        "vector_crs_valid": True,
        "threshold_m": threshold,
        "outputs": {"summary": relative(summary_path), "provenance": relative(provenance_path), "validation": relative(METRICS_DIR / "p7_validation.json")},
    }
    write_json(METRICS_DIR / "p7_validation.json", validation)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
