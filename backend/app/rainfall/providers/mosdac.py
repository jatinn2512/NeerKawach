"""Read the INSAT-3DR IMC subset while preserving the two native pixel supports."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.rainfall.contracts import NativeGrid, RainfallRecord, RainfallSeries, RainfallValidationError, validate_records
from app.rainfall.registry import relative_path
from .file import LocalFileProvider

SOURCE_ID = "mosdac_insat3dr"
PRODUCT = "3RIMG_L2B_IMC"
FILENAME = re.compile(r"^3RIMG_(\d{2}[A-Z]{3}\d{4}_\d{4})_L2B_IMC_.*\.tif$")
DEPTH_ASSUMPTION = "Rate multiplied by 0.5 h, assuming it represents the nominal half-hour."


def source_label(path: Path) -> str:
    match = FILENAME.fullmatch(path.name)
    if not match:
        raise RainfallValidationError(f"invalid MOSDAC filename: {path.name}")
    return match[1]


def parse_timestamp(path: Path) -> str:
    value = datetime.strptime(source_label(path), "%d%b%Y_%H%M").replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def pixel_record(path: Path, timestamp: str, label: str, grid: NativeGrid, row: int, col: int,
                 bbox: dict, rate: float | None, resolution: int, flag: str) -> RainfallRecord:
    geometry = grid.pixel(row, col)
    west, south, east, north = geometry["footprint"]
    west, east = max(west, bbox["min_lon"]), min(east, bbox["max_lon"])
    south, north = max(south, bbox["min_lat"]), min(north, bbox["max_lat"])
    if east <= west or north <= south:
        raise RainfallValidationError("pixel does not intersect the configured geographic subset")
    geometry["subset_bbox"] = bbox
    depth = None if rate is None else rate * 0.5
    return RainfallRecord(
        timestamp, (south + north) / 2, (west + east) / 2, depth, SOURCE_ID, product=PRODUCT,
        source_file=relative_path(path), source_record_id=f"{timestamp}/{row}/{col}", variable="IMC",
        measurement_type="rainfall_rate", original_value=rate, original_unit="mm/h",
        rainfall_rate_mm_h=rate, derived_value=depth, derived_unit="mm", derivation=DEPTH_ASSUMPTION,
        source_label=label, cadence_seconds=1800, timestamp_convention="filename interpreted as UTC; interval anchor and rate averaging unknown",
        geometry=geometry, spatial_resolution=str(resolution), native_resolution_m=float(resolution),
        units="mm per 30-minute accumulation",
        missing=rate is None, quality_flags=(flag,), observed=True, mode="historical_observed_satellite_estimate",
        provenance={"provider": "MOSDAC / ISRO", "unit_basis": "repository IMC product interpretation"},
    )


class MosdacProvider(LocalFileProvider):
    source_id = SOURCE_ID

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return (".tif", ".tiff", ".csv")

    @staticmethod
    def frame(dataset, path: Path, bbox: dict, resolution: int) -> list[RainfallRecord]:
        """Rasterio is required only by callers reading a GeoTIFF."""
        transform = dataset.transform
        if (dataset.count != 1 or str(dataset.crs) != "EPSG:4326" or transform.b or transform.d
                or transform.a <= 0 or transform.e >= 0):
            raise RainfallValidationError("unsupported MOSDAC grid or band layout")
        grid = NativeGrid(str(dataset.crs), dataset.width, dataset.height, transform.c, transform.f,
                          transform.a, transform.e, dataset.nodata)
        timestamp, label = parse_timestamp(path), source_label(path)
        data = dataset.read(1, masked=True)
        result = []
        for row, col in grid.intersecting_pixels(bbox):
            if data.mask.shape and data.mask[row, col]:
                rate, flag = None, "nodata"
            else:
                value = float(data[row, col])
                rate = value if math.isfinite(value) and value >= 0 else None
                flag = "valid_source_pixel" if rate is not None else "invalid_source_value"
            result.append(pixel_record(path, timestamp, label, grid, row, col, bbox, rate, resolution, flag))
        return result

    def read_subset(self, path: Path, metadata_path: Path) -> RainfallSeries:
        """Restore native geometry from the checked-in CSV and its ingestion manifest."""
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        raster = metadata["source_raster"]
        if (raster["crs"] != "EPSG:4326" or metadata.get("source", SOURCE_ID) != SOURCE_ID
                or metadata.get("source_product", PRODUCT) != PRODUCT):
            raise RainfallValidationError("unexpected MOSDAC dataset or CRS in manifest")
        bounds = raster["raw_extent"]
        width, height = raster["dimensions"]
        grid = NativeGrid(raster["crs"], width, height, bounds["left"], bounds["top"],
                          (bounds["right"] - bounds["left"]) / width,
                          (bounds["bottom"] - bounds["top"]) / height, raster["nodata"])
        frames = {item["timestamp_utc"]: item for item in metadata["records"]}
        if len(frames) != len(metadata["records"]):
            raise RainfallValidationError("duplicate timestamp in MOSDAC manifest")
        result = []
        for legacy in self.read_csv(path):
            if (legacy.product not in (None, PRODUCT) or legacy.units not in ("mm", "mm per 30-minute accumulation")
                    or legacy.rainfall_rate_mm_h is None):
                raise RainfallValidationError("MOSDAC subset does not contain the expected product, rate and depth")
            ts = legacy.timestamp_utc
            if ts not in frames:
                raise RainfallValidationError("MOSDAC CSV timestamp missing from file manifest")
            raw = Path(frames[ts]["file"])
            if parse_timestamp(raw) != ts:
                raise RainfallValidationError("MOSDAC filename and CSV timestamps disagree")
            lon = float(legacy.extra["source_pixel_longitude"])
            lat = float(legacy.extra["source_pixel_latitude"])
            col, row = math.floor((lon - grid.west) / grid.dx), math.floor((lat - grid.origin_y) / grid.dy)
            record = pixel_record(raw, ts, source_label(raw), grid, row, col, metadata["study_area"]["bbox"],
                                  legacy.rainfall_rate_mm_h, raster["native_resolution_m"], "valid_source_pixel")
            x, y = record.geometry["center"]
            if (record.rainfall_mm != legacy.rainfall_mm or abs(x-lon) > 1e-9 or abs(y-lat) > 1e-9
                    or abs(record.latitude-legacy.latitude) > 1e-9 or abs(record.longitude-legacy.longitude) > 1e-9):
                raise RainfallValidationError("MOSDAC pixel geometry or derived depth disagrees with CSV")
            result.append(replace(record, quality_flags=legacy.quality_flags or record.quality_flags,
                                  provenance={**record.provenance, "subset_file": relative_path(path),
                                              "metadata_file": relative_path(metadata_path)}))
        counts = Counter(r.timestamp_utc for r in result)
        if any(counts[ts] != frame["valid_pixels"] for ts, frame in frames.items()):
            raise RainfallValidationError("MOSDAC CSV pixel counts disagree with file manifest")
        # A legacy CSV only retained valid pixels. The manifest distinguishes a
        # delivered frame with an omitted pixel from an entirely absent frame.
        bbox = metadata["study_area"]["bbox"]
        for ts, frame in frames.items():
            if frame["valid_pixels"] == frame["pixels_intersecting_aoi"]:
                continue
            raw = Path(frame["file"])
            present = {(r.geometry["row"], r.geometry["column"]) for r in result if r.timestamp_utc == ts}
            for row, col in grid.intersecting_pixels(bbox):
                if (row, col) not in present:
                    result.append(pixel_record(raw, ts, source_label(raw), grid, row, col, bbox,
                                               None, raster["native_resolution_m"], "missing_from_normalized_subset"))
        return RainfallSeries(sorted(validate_records(result), key=lambda r: r.source_record_id),
                              metadata["temporal_coverage"]["missing_timestamps"])
