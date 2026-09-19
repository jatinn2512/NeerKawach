"""Prepare the P2 DEM foundation from the preserved SRTM HGT tile.

This script intentionally stops at GeoTIFF preparation, buffering, exact
canonical-bbox clipping and validation. It does not calculate terrain
derivatives or perform any hydrologic/flood modelling.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "study_area.json"
DEM_METADATA_PATH = ROOT / "data" / "dem" / "metadata" / "srtm_n12e077.json"
RAW_PATH = ROOT / "data" / "dem" / "raw" / "N12E077.hgt.gz"
OUTPUT_DIR = ROOT / "data" / "dem" / "processed"
SOURCE_TIF = OUTPUT_DIR / "bellandur_dem_source.tif"
BUFFERED_TIF = OUTPUT_DIR / "bellandur_dem_buffered.tif"
CLIPPED_TIF = OUTPUT_DIR / "bellandur_dem_clipped.tif"
REPORT_PATH = ROOT / "data" / "dem" / "metadata" / "bellandur_dem_processed.json"

SCRIPT_VERSION = "p2-dem-preparation-1.0.0"
BUFFER_DISTANCE_M = 300.0
HGT_RESOLUTION_DEGREES = 1.0 / 3600.0
HGT_MIN_LON = 77.0
HGT_MAX_LAT = 13.0
HGT_ROWS = 3601
HGT_COLS = 3601
HGT_NODATA = -32768


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_inputs() -> tuple[dict, dict]:
    area = load_json(CONFIG_PATH)
    metadata = load_json(DEM_METADATA_PATH)
    if area.get("crs") != "EPSG:4326":
        raise ValueError("The canonical study area must use EPSG:4326")
    bbox = area["bbox"]
    if not (bbox["min_lat"] < bbox["max_lat"] and bbox["min_lon"] < bbox["max_lon"]):
        raise ValueError("The canonical study-area bbox is invalid")
    if metadata.get("crs") != "EPSG:4326":
        raise ValueError("The raw DEM metadata does not identify EPSG:4326")
    if metadata.get("rows") != HGT_ROWS or metadata.get("columns") != HGT_COLS:
        raise ValueError("Raw HGT dimensions do not match the P1 metadata")
    tile = metadata.get("tile_extent", {})
    if not all((tile.get("min_lat", 0) <= bbox["min_lat"], tile.get("max_lat", 0) >= bbox["max_lat"], tile.get("min_lon", 0) <= bbox["min_lon"], tile.get("max_lon", 0) >= bbox["max_lon"])):
        raise ValueError("Raw DEM tile does not cover the canonical study area")
    if not RAW_PATH.exists():
        raise FileNotFoundError(RAW_PATH)
    return area, metadata


def read_hgt() -> np.ndarray:
    """Read big-endian signed 16-bit SRTM postings without altering the raw file."""
    with gzip.open(RAW_PATH, "rb") as handle:
        payload = handle.read()
    expected_bytes = HGT_ROWS * HGT_COLS * 2
    if len(payload) != expected_bytes:
        raise ValueError(f"Expected {expected_bytes} HGT bytes, received {len(payload)}")
    values = np.frombuffer(payload, dtype=">i2").reshape((HGT_ROWS, HGT_COLS))
    return values.astype(np.int16, copy=True)


def buffer_bbox(bbox: dict, distance_m: float) -> dict:
    mid_lat = math.radians((bbox["min_lat"] + bbox["max_lat"]) / 2.0)
    lat_delta = distance_m / 111320.0
    lon_delta = distance_m / (111320.0 * math.cos(mid_lat))
    return {
        "min_lat": bbox["min_lat"] - lat_delta,
        "min_lon": bbox["min_lon"] - lon_delta,
        "max_lat": bbox["max_lat"] + lat_delta,
        "max_lon": bbox["max_lon"] + lon_delta,
    }


def aligned_window(bbox: dict) -> tuple[slice, dict]:
    """Return a source-posting window whose geospatial bounds cover bbox."""
    def lower_index(value: float) -> int:
        ratio = value / HGT_RESOLUTION_DEGREES
        nearest = round(ratio)
        return nearest if math.isclose(ratio, nearest, rel_tol=0, abs_tol=1e-9) else math.floor(ratio)

    def upper_index(value: float) -> int:
        ratio = value / HGT_RESOLUTION_DEGREES
        nearest = round(ratio)
        return nearest if math.isclose(ratio, nearest, rel_tol=0, abs_tol=1e-9) else math.ceil(ratio)

    col_start = lower_index(bbox["min_lon"] - HGT_MIN_LON)
    col_stop = upper_index(bbox["max_lon"] - HGT_MIN_LON)
    row_start = lower_index(HGT_MAX_LAT - bbox["max_lat"])
    row_stop = upper_index(HGT_MAX_LAT - bbox["min_lat"])
    col_start = max(0, min(HGT_COLS - 1, col_start))
    col_stop = max(col_start + 1, min(HGT_COLS, col_stop))
    row_start = max(0, min(HGT_ROWS - 1, row_start))
    row_stop = max(row_start + 1, min(HGT_ROWS, row_stop))
    extent = {
        "min_lon": HGT_MIN_LON + col_start * HGT_RESOLUTION_DEGREES,
        "max_lon": HGT_MIN_LON + col_stop * HGT_RESOLUTION_DEGREES,
        "max_lat": HGT_MAX_LAT - row_start * HGT_RESOLUTION_DEGREES,
        "min_lat": HGT_MAX_LAT - row_stop * HGT_RESOLUTION_DEGREES,
    }
    return (slice(row_start, row_stop), slice(col_start, col_stop)), extent


def write_geotiff(path: Path, values: np.ndarray, extent: dict, area_or_point: str = "Point") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(extent["min_lon"], extent["max_lat"], HGT_RESOLUTION_DEGREES, HGT_RESOLUTION_DEGREES)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=transform,
        nodata=HGT_NODATA,
        compress="deflate",
        predictor=2,
        BIGTIFF="IF_SAFER",
    ) as dataset:
        dataset.write(values.astype(np.int16, copy=False), 1)
        dataset.update_tags(AREA_OR_POINT=area_or_point, SOURCE_FORMAT="SRTM HGT big-endian int16 postings")


def raster_report(path: Path, expected_bbox: dict | None = None) -> dict:
    with rasterio.open(path) as dataset:
        values = dataset.read(1)
        bounds = dataset.bounds
        nodata = dataset.nodata
        valid_mask = values != nodata if nodata is not None else np.ones(values.shape, dtype=bool)
        valid_mask &= np.isfinite(values)
        valid = values[valid_mask]
        if valid.size == 0:
            raise ValueError(f"Raster has no valid pixels: {path}")
        extent = {"min_lon": bounds.left, "min_lat": bounds.bottom, "max_lon": bounds.right, "max_lat": bounds.top}
        report = {
            "file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "pixel_size_degrees": [abs(dataset.transform.a), abs(dataset.transform.e)],
            "extent": extent,
            "nodata": nodata,
            "minimum_elevation_m": int(valid.min()),
            "maximum_elevation_m": int(valid.max()),
            "valid_pixel_count": int(valid.size),
            "nodata_pixel_count": int(values.size - valid.size),
            "total_pixel_count": int(values.size),
            "all_pixels_valid": bool(valid.size == values.size),
        }
        if expected_bbox is not None:
            tolerance = HGT_RESOLUTION_DEGREES * 1e-6
            covers = (
                bounds.left <= expected_bbox["min_lon"] + tolerance
                and bounds.right >= expected_bbox["max_lon"] - tolerance
                and bounds.bottom <= expected_bbox["min_lat"] + tolerance
                and bounds.top >= expected_bbox["max_lat"] - tolerance
            )
            report["covers_expected_bbox"] = bool(covers)
            if not covers:
                raise ValueError(f"Raster does not cover expected bbox: {path}")
        if report["nodata_pixel_count"]:
            raise ValueError(f"Unexpected nodata pixels in prepared raster: {path}")
        if report["crs"] != "EPSG:4326":
            raise ValueError(f"Unexpected CRS in prepared raster: {path}")
        if not all(math.isclose(value, HGT_RESOLUTION_DEGREES, rel_tol=0, abs_tol=1e-12) for value in report["pixel_size_degrees"]):
            raise ValueError(f"Unexpected pixel size in prepared raster: {path}")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buffer-m", type=float, default=BUFFER_DISTANCE_M, help="buffer distance in metres (default: 300)")
    args = parser.parse_args()
    if args.buffer_m <= 0:
        raise ValueError("--buffer-m must be positive")
    area, source_metadata = load_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    values = read_hgt()
    source_extent = {"min_lon": 77.0, "min_lat": 12.0, "max_lon": 78.0, "max_lat": 13.0}
    write_geotiff(SOURCE_TIF, values, source_extent)

    buffered_bbox = buffer_bbox(area["bbox"], args.buffer_m)
    buffered_window, buffered_extent = aligned_window(buffered_bbox)
    write_geotiff(BUFFERED_TIF, values[buffered_window], buffered_extent)

    clipped_window, clipped_extent = aligned_window(area["bbox"])
    write_geotiff(CLIPPED_TIF, values[clipped_window], clipped_extent)

    source_report = raster_report(SOURCE_TIF)
    buffered_report = raster_report(BUFFERED_TIF, area["bbox"])
    clipped_report = raster_report(CLIPPED_TIF, area["bbox"])
    if not clipped_report["all_pixels_valid"]:
        raise ValueError("Final clipped DEM contains empty pixels")

    mid_lat = math.radians((area["bbox"]["min_lat"] + area["bbox"]["max_lat"]) / 2.0)
    report = {
        "processing_script": SCRIPT_VERSION,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "source_dataset": source_metadata.get("dataset"),
        "source_url": source_metadata.get("source_url"),
        "source_file": str(RAW_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_format": "SRTM HGT, big-endian signed int16 elevation postings",
        "source_hgt_extent": source_extent,
        "source_nodata": source_metadata.get("nodata_value", HGT_NODATA),
        "crs": "EPSG:4326",
        "pixel_size_degrees": [HGT_RESOLUTION_DEGREES, HGT_RESOLUTION_DEGREES],
        "approximate_pixel_size_m": {"north_south": HGT_RESOLUTION_DEGREES * 111320.0, "east_west_at_study_area": HGT_RESOLUTION_DEGREES * 111320.0 * math.cos(mid_lat)},
        "canonical_study_area_bbox": area["bbox"],
        "buffer_distance_m": args.buffer_m,
        "buffered_bbox_requested": buffered_bbox,
        "buffered_extent": buffered_extent,
        "outputs": {
            "source_geotiff": source_report,
            "buffered_geotiff": buffered_report,
            "clipped_geotiff": clipped_report,
        },
        "validation": {
            "raw_source_preserved": RAW_PATH.exists(),
            "crs_verified": clipped_report["crs"] == "EPSG:4326",
            "resolution_verified": clipped_report["pixel_size_degrees"] == [HGT_RESOLUTION_DEGREES, HGT_RESOLUTION_DEGREES],
            "canonical_bbox_covered": clipped_report["covers_expected_bbox"],
            "no_unexpected_empty_pixels": clipped_report["all_pixels_valid"],
        },
        "processing_scope": "HGT decompression, GeoTIFF conversion, aligned 300 m buffered preparation, exact canonical-bbox clipping and validation only; no terrain derivatives or flood modelling.",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
