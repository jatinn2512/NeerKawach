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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.rainfall.providers.mosdac import MosdacProvider, PRODUCT, SOURCE_ID, parse_timestamp
from app.rainfall.registry import relative_path

STUDY_AREA = ROOT / "config" / "study_area.json"
REGISTRY = ROOT / "config" / "rainfall_sources.json"
def rel(path: Path) -> str:
    return relative_path(path)


def load_config() -> tuple[dict, dict, Path, Path]:
    area = json.loads(STUDY_AREA.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source = registry["sources"][SOURCE_ID]
    raw_root = ROOT / source["raw_directory"]
    output_root = ROOT / source["processed_directory"]
    return area, source, raw_root, output_root


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
            pixels = MosdacProvider.frame(dataset, path, bbox, int(source["native_resolution_m"]))
            selected = len(pixels)
            valid = nonzero = 0
            for pixel in pixels:
                aoi_pixel_bounds.append(pixel.geometry["footprint"])
                if pixel.missing:
                    continue
                source_lon, source_lat = pixel.geometry["center"]
                rows.append({
                    "timestamp_utc": timestamp, "timestamp": timestamp,
                    "lat": pixel.latitude, "lon": pixel.longitude,
                    "latitude": pixel.latitude, "longitude": pixel.longitude,
                    "source_pixel_latitude": source_lat, "source_pixel_longitude": source_lon,
                    "rainfall_mm": pixel.rainfall_mm, "rainfall_rate_mm_per_hr": pixel.original_value,
                    "source": SOURCE_ID, "source_product": PRODUCT,
                    "resolution_m": int(pixel.spatial_resolution), "units": pixel.units,
                    "quality_flag": pixel.quality_flags[0], "is_observed": True,
                    "is_forecast": False, "is_fallback": False, "mode": pixel.mode,
                })
                valid += 1
                nonzero += int(pixel.original_value > 0)
                raw_values.append(pixel.rainfall_mm)
                rate_values.append(pixel.original_value)
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
