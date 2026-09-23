"""Validate and normalize the local MOSDAC INSAT-3DR IMC GeoTIFF set.

The source product is a half-hourly satellite precipitation estimate. The
GeoTIFF values are treated as rain rate in mm/hour, as documented for IMSRA;
the normalized ``rainfall_mm`` field is the corresponding 30-minute
accumulation. Pixels are retained when their footprints intersect the exact
canonical Bellandur bbox. Raw files are never changed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[2]
STUDY_AREA = ROOT / "config" / "study_area.json"
REGISTRY = ROOT / "config" / "rainfall_sources.json"
SOURCE_ID = "mosdac_insat3dr"
PRODUCT = "3RIMG_L2B_IMC"
TIMESTAMP_RE = re.compile(r"^3RIMG_(\d{2})([A-Z]{3})(\d{4})_(\d{2})(\d{2})_L2B_IMC_.*\.tif$")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def parse_timestamp(path: Path) -> str:
    match = TIMESTAMP_RE.match(path.name)
    if not match:
        raise ValueError(f"cannot parse MOSDAC timestamp from {path.name}")
    value = datetime.strptime("".join(match.groups()), "%d%b%Y%H%M").replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def load_config() -> tuple[dict, dict, Path, Path]:
    area = json.loads(STUDY_AREA.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source = registry["sources"][SOURCE_ID]
    raw_root = ROOT / source["raw_directory"]
    output_root = ROOT / source["processed_directory"]
    return area, source, raw_root, output_root


def pixel_intersects(transform, row: int, col: int, bbox: dict[str, float]) -> bool:
    left = transform.c + col * transform.a
    right = left + transform.a
    top = transform.f + row * transform.e
    bottom = top + transform.e
    west, east = sorted((left, right))
    south, north = sorted((bottom, top))
    return not (east < bbox["min_lon"] or west > bbox["max_lon"] or north < bbox["min_lat"] or south > bbox["max_lat"])


def run(output_csv: Path | None = None, metadata_json: Path | None = None) -> dict:
    area, source, raw_root, output_root = load_config()
    bbox = area["bbox"]
    files = sorted(raw_root.glob(source["raw_file_pattern"]))
    expected = int(source["expected_file_count"])
    if len(files) != expected:
        raise ValueError(f"MOSDAC file count mismatch: expected {expected}, found {len(files)}")
    if not files:
        raise ValueError("No MOSDAC GeoTIFF files found")

    output_csv = output_csv or output_root / "mosdac_bellandur.csv"
    metadata_json = metadata_json or ROOT / "data" / "rainfall" / "metadata" / "mosdac_bellandur.json"
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    metadata_json.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    timestamps: list[str] = []
    source_stats: list[dict[str, object]] = []
    profile_signature: tuple | None = None
    crop_signature: tuple | None = None
    raw_extent: dict[str, float] | None = None
    aoi_pixel_bounds: list[tuple[float, float, float, float]] = []
    raw_values: list[float] = []
    rate_values: list[float] = []
    invalid_files: list[str] = []

    for path in files:
        timestamp = parse_timestamp(path)
        timestamps.append(timestamp)
        with rasterio.open(path) as dataset:
            signature = (dataset.count, dataset.width, dataset.height, str(dataset.crs), dataset.dtypes[0], dataset.nodata, tuple(round(value, 12) for value in dataset.transform))
            if profile_signature is None:
                profile_signature = signature
            elif signature != profile_signature:
                raise ValueError(f"MOSDAC raster profile mismatch in {path.name}")
            bounds = dataset.bounds
            if raw_extent is None:
                raw_extent = {"left": float(bounds.left), "bottom": float(bounds.bottom), "right": float(bounds.right), "top": float(bounds.top)}
            if bounds.left > bbox["min_lon"] or bounds.right < bbox["max_lon"] or bounds.bottom > bbox["min_lat"] or bounds.top < bbox["max_lat"]:
                raise ValueError(f"MOSDAC raster does not cover the canonical bbox: {path.name}")
            data = dataset.read(1, masked=True).astype(np.float64)
            selected = 0
            valid = 0
            nonzero = 0
            for row_index in range(dataset.height):
                for col_index in range(dataset.width):
                    if not pixel_intersects(dataset.transform, row_index, col_index, bbox):
                        continue
                    selected += 1
                    left = dataset.transform.c + col_index * dataset.transform.a
                    right = left + dataset.transform.a
                    top = dataset.transform.f + row_index * dataset.transform.e
                    bottom = top + dataset.transform.e
                    aoi_pixel_bounds.append((min(left, right), min(bottom, top), max(left, right), max(bottom, top)))
                    pixel_west, pixel_east = sorted((left, right))
                    pixel_south, pixel_north = sorted((bottom, top))
                    intersection_west = max(pixel_west, bbox["min_lon"])
                    intersection_east = min(pixel_east, bbox["max_lon"])
                    intersection_south = max(pixel_south, bbox["min_lat"])
                    intersection_north = min(pixel_north, bbox["max_lat"])
                    value = data[row_index, col_index]
                    if np.ma.is_masked(value) or not math.isfinite(float(value)) or float(value) < 0:
                        continue
                    rate = float(value)
                    accumulation = rate * 0.5
                    source_center_x, source_center_y = rasterio.transform.xy(dataset.transform, row_index, col_index, offset="center")
                    center_x = (intersection_west + intersection_east) / 2.0
                    center_y = (intersection_south + intersection_north) / 2.0
                    row = {
                        "timestamp_utc": timestamp,
                        "timestamp": timestamp,
                        "lat": float(center_y),
                        "lon": float(center_x),
                        "latitude": float(center_y),
                        "longitude": float(center_x),
                        "source_pixel_latitude": float(source_center_y),
                        "source_pixel_longitude": float(source_center_x),
                        "rainfall_mm": accumulation,
                        "rainfall_rate_mm_per_hr": rate,
                        "source": SOURCE_ID,
                        "source_product": PRODUCT,
                        "resolution_m": int(source["native_resolution_m"]),
                        "units": "mm per 30-minute accumulation",
                        "quality_flag": "valid_source_pixel",
                        "is_observed": True,
                        "is_forecast": False,
                        "is_fallback": False,
                        "mode": "historical_observed_satellite_estimate",
                    }
                    rows.append(row)
                    valid += 1
                    nonzero += int(rate != 0)
                    raw_values.append(accumulation)
                    rate_values.append(rate)
            if crop_signature is None:
                crop_signature = (selected, tuple(round(value, 12) for value in dataset.bounds))
            if valid == 0:
                invalid_files.append(path.name)
            source_stats.append({"file": rel(path), "timestamp_utc": timestamp, "pixels_intersecting_aoi": selected, "valid_pixels": valid, "nonzero_pixels": nonzero})

    if invalid_files:
        raise ValueError(f"MOSDAC files contain no valid Bellandur pixels: {invalid_files[:5]}")
    timestamps.sort()
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("MOSDAC timestamps are duplicated")

    fields = list(rows[0].keys())
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    time_values = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in timestamps]
    gaps_minutes = sorted({int((later - earlier).total_seconds() / 60) for earlier, later in zip(time_values, time_values[1:])})
    expected_start = datetime.fromisoformat(source["historical_coverage_start_utc"].replace("Z", "+00:00"))
    expected_end = datetime.fromisoformat(source["historical_coverage_end_utc"].replace("Z", "+00:00"))
    expected_timestamps = []
    cursor = expected_start
    while cursor <= expected_end:
        expected_timestamps.append(cursor.isoformat().replace("+00:00", "Z"))
        cursor += timedelta(minutes=30)
    observed_timestamp_set = set(timestamps)
    expected_timestamp_set = set(expected_timestamps)
    missing_timestamps = [value for value in expected_timestamps if value not in observed_timestamp_set]
    unexpected_timestamps = sorted(observed_timestamp_set - expected_timestamp_set)
    metadata = {
        "source": SOURCE_ID,
        "source_product": PRODUCT,
        "provider": "MOSDAC / ISRO Space Applications Centre",
        "source_url": "https://mosdac.gov.in/doi/195/",
        "documentation_url": "https://mosdac.gov.in/docs/INSAT_3D_ATBD_MAY_2015.pdf",
        "raw_directory": rel(raw_root),
        "raw_file_count": len(files),
        "raw_files_preserved": True,
        "processed_file": rel(output_csv),
        "metadata_file": rel(metadata_json),
        "study_area": {"bbox": bbox, "crs": area["crs"]},
        "source_raster": {"dimensions": [profile_signature[1], profile_signature[2]], "count": profile_signature[0], "crs": profile_signature[3], "dtype": profile_signature[4], "nodata": profile_signature[5], "native_resolution_m": source["native_resolution_m"], "raw_extent": raw_extent},
        "aoi_handling": {"method": "retain source pixels whose geographic footprints intersect canonical bbox; represent each intersecting footprint by its clipped-AOI intersection centroid", "pixels_per_timestamp": crop_signature[0], "intersecting_pixel_extent": {"left": min(item[0] for item in aoi_pixel_bounds), "bottom": min(item[1] for item in aoi_pixel_bounds), "right": max(item[2] for item in aoi_pixel_bounds), "top": max(item[3] for item in aoi_pixel_bounds)}, "additional_raster_clip_required": False, "source_rasters_are_aoi_clipped": False},
        "temporal_coverage": {"start_utc": timestamps[0], "end_utc": timestamps[-1], "expected_start_utc": expected_timestamps[0], "expected_end_utc": expected_timestamps[-1], "expected_timestamp_count": len(expected_timestamps), "unique_timestamps": len(timestamps), "nominal_interval_minutes": 30, "observed_gap_intervals_minutes": gaps_minutes, "missing_timestamp_count": len(missing_timestamps), "missing_timestamps": missing_timestamps, "unexpected_timestamps": unexpected_timestamps, "gaps_are_source_data_gaps": bool(missing_timestamps and not unexpected_timestamps), "gap_assessment": "Missing slots correspond to absent source GeoTIFF filenames; the ingestion process does not interpolate, fill, or silently discard timestamps." if missing_timestamps else "No temporal gaps detected."},
        "value_interpretation": {"raw_value_units": "mm/hour rain rate", "normalized_rainfall_mm": "raw rain rate multiplied by 0.5 hour", "normalized_units": "mm per 30-minute accumulation", "rainfall_rate_preserved": True},
        "statistics": {"normalized_min_mm": min(raw_values), "normalized_max_mm": max(raw_values), "normalized_mean_mm": float(np.mean(raw_values)), "rate_min_mm_per_hr": min(rate_values), "rate_max_mm_per_hr": max(rate_values), "rate_mean_mm_per_hr": float(np.mean(rate_values)), "nonzero_record_count": sum(value > 0 for value in rate_values), "record_count": len(rows)},
        "validation": {"all_files_readable": True, "all_profiles_identical": True, "all_files_cover_bbox": True, "all_timestamps_unique": True, "invalid_files": invalid_files},
        "records": source_stats,
        "model_input_compatibility": {"p3_surface_routing": True, "format": "normalized CSV with timestamp/latitude/longitude/rainfall_mm/source", "timestep_seconds": 1800, "p5": "not substituted; validated P5 remains explicitly synthetic-fixture-only"},
    }
    metadata_json.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--metadata-json", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output_csv, args.metadata_json), indent=2))


if __name__ == "__main__":
    main()
