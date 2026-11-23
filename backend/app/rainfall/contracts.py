"""Rainfall measurements at their native spatial and temporal support."""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .registry import relative_path


class RainfallValidationError(ValueError):
    """A record or its source metadata cannot be interpreted safely."""


def utc_label(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RainfallValidationError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RainfallValidationError("UTC timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class NativeGrid:
    """Axis-aligned source grid. The six transform coefficients use GDAL order."""
    crs: str
    width: int
    height: int
    west: float
    origin_y: float
    dx: float
    dy: float
    nodata: float | None

    def intersecting_pixels(self, bbox: dict):
        """Select native cells in a lon/lat rectangle without computing area weights."""
        for row in range(self.height):
            y = self.origin_y + row * self.dy
            south, north = sorted((y, y + self.dy))
            if south >= bbox["max_lat"] or north <= bbox["min_lat"]:
                continue
            for col in range(self.width):
                west = self.west + col * self.dx
                if west < bbox["max_lon"] and west + self.dx > bbox["min_lon"]:
                    yield row, col

    def pixel(self, row: int, col: int) -> dict:
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise RainfallValidationError("pixel outside native grid")
        x, y = self.west + col * self.dx, self.origin_y + row * self.dy
        end_y = self.origin_y + self.height * self.dy
        return {
            "kind": "grid_cell", "crs": self.crs, "row": row, "column": col,
            "center": (x + self.dx / 2, y + self.dy / 2),
            "footprint": (x, min(y, y + self.dy), x + self.dx, max(y, y + self.dy)),
            "raster_bounds": (self.west, min(self.origin_y, end_y),
                              self.west + self.width * self.dx, max(self.origin_y, end_y)),
            "transform_gdal": (self.west, self.dx, 0.0, self.origin_y, 0.0, self.dy),
            "dimensions": (self.width, self.height), "nodata": self.nodata,
        }


@dataclass(frozen=True)
class RainfallRecord:
    timestamp_utc: str | None
    latitude: float
    longitude: float
    rainfall_mm: float | None
    source: str
    product: str | None = None
    rainfall_rate_mm_h: float | None = None
    spatial_resolution: str | None = None
    native_resolution_m: float | None = None
    units: str = "mm"
    quality_flags: tuple[str, ...] = ()
    observed: bool = False
    forecast: bool = False
    fallback: bool = False
    station_id: str | None = None
    mode: str | None = None
    extra: dict[str, Any] | None = None
    source_file: str | None = None
    source_record_id: str | None = None
    variable: str | None = None
    measurement_type: str = "unknown"
    original_value: float | None = None
    original_unit: str | None = None
    derived_value: float | None = None
    derived_unit: str | None = None
    derivation: str | None = None
    source_label: str | None = None
    reported_date: str | None = None
    timestamp_convention: str = "unknown"
    cadence_seconds: int | None = None
    interval_seconds: int | None = None
    interval_start_utc: str | None = None
    interval_end_utc: str | None = None
    forecast_valid_utc: str | None = None
    retrieved_at_utc: str | None = None
    model_issue_utc: str | None = None
    freshness: str | None = None
    geometry: dict | None = None
    provenance: dict = field(default_factory=dict)
    missing: bool = False

    def __post_init__(self):
        if not isinstance(self.source, str) or not self.source.strip():
            raise RainfallValidationError("rainfall requires a source identifier")
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise RainfallValidationError("invalid source or geographic coordinates")
        if self.observed and self.forecast:
            raise RainfallValidationError("forecast and observed are mutually exclusive")
        if self.reported_date:
            date.fromisoformat(self.reported_date)
        if self.timestamp_utc is None and not self.reported_date:
            raise RainfallValidationError("expected a UTC label or provider-reported date")
        for name in ("timestamp_utc", "interval_start_utc", "interval_end_utc",
                     "forecast_valid_utc", "retrieved_at_utc", "model_issue_utc"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, utc_label(value))
        for duration in (self.cadence_seconds, self.interval_seconds):
            if duration is not None and (not math.isfinite(duration) or duration <= 0):
                raise RainfallValidationError("rainfall durations must be finite and positive")
        if self.interval_start_utc and self.interval_end_utc:
            elapsed = datetime.fromisoformat(self.interval_end_utc) - datetime.fromisoformat(self.interval_start_utc)
            if elapsed.total_seconds() <= 0 or (self.interval_seconds and elapsed.total_seconds() != self.interval_seconds):
                raise RainfallValidationError("interval bounds disagree with duration")
        if self.missing != (self.rainfall_mm is None):
            raise RainfallValidationError("missing records must have null rainfall")
        for value in (self.rainfall_mm, self.original_value, self.rainfall_rate_mm_h, self.derived_value):
            if value is not None and (self.missing or not math.isfinite(value) or value < 0):
                raise RainfallValidationError("rainfall cannot be negative, nonfinite or populated when missing")
        native_units = {"rainfall_rate": "mm/h", "interval_accumulation": "mm",
                        "daily_accumulation": "mm", "forecast_accumulation": "mm"}
        if self.measurement_type != "unknown":
            if (self.measurement_type not in native_units or self.original_unit != native_units[self.measurement_type]
                    or (self.original_value is None and not self.missing)):
                raise RainfallValidationError("invalid original unit or value for measurement type")
        if self.measurement_type == "forecast_accumulation" and not (self.forecast and self.forecast_valid_utc):
            raise RainfallValidationError("forecast accumulation requires a forecast valid time")
        if self.derived_value is not None and not (self.derived_unit and self.derivation):
            raise RainfallValidationError("derived value requires units and an explicit derivation")

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("extra")
        row.update(timestamp=self.timestamp_utc, lat=self.latitude, lon=self.longitude,
                   source_product=self.product, rainfall_rate_mm_per_hr=self.rainfall_rate_mm_h,
                   resolution_m=self.native_resolution_m, quality_flags=list(self.quality_flags),
                   quality_flag=";".join(self.quality_flags), is_observed=self.observed,
                   is_forecast=self.forecast, is_fallback=self.fallback,
                   mode=self.mode or ("forecast" if self.forecast else "observed" if self.observed else "unknown"))
        return row


@dataclass
class RainfallSeries:
    records: list[RainfallRecord]
    missing_labels: list[str] = field(default_factory=list)
    captures: list[dict] = field(default_factory=list)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def normalize_record(row: dict[str, Any], *, source: str | None = None, bbox: dict | None = None) -> RainfallRecord:
    if row.get("timestamp_utc") and row.get("timestamp") and utc_label(row["timestamp_utc"]) != utc_label(row["timestamp"]):
        raise RainfallValidationError("timestamp aliases disagree")
    if source and row.get("source") and source != row["source"]:
        raise RainfallValidationError("record belongs to a different rainfall source")
    values = {f.name: row[f.name] for f in fields(RainfallRecord) if f.name in row}
    values.update(source=source or row.get("source"), timestamp_utc=row.get("timestamp_utc", row.get("timestamp")),
                  product=row.get("product") or row.get("source_product"),
                  spatial_resolution=row.get("spatial_resolution", row.get("resolution_m")))
    values.setdefault("source_label", row.get("timestamp", row.get("timestamp_utc")))
    try:
        values["latitude"] = float(row.get("latitude", row.get("lat")))
        values["longitude"] = float(row.get("longitude", row.get("lon")))
        for key in ("observed", "forecast", "fallback", "missing"):
            values[key] = _bool(row.get(key, row.get("is_" + key, False)))
        values["rainfall_mm"] = None if values["missing"] and row.get("rainfall_mm") is None else float(row["rainfall_mm"])
        values["rainfall_rate_mm_h"] = row.get("rainfall_rate_mm_h", row.get("rainfall_rate_mm_per_hr"))
        values["native_resolution_m"] = row.get("native_resolution_m", row.get("resolution_m"))
        for key in ("rainfall_rate_mm_h", "original_value", "derived_value", "native_resolution_m"):
            if values.get(key) is not None:
                values[key] = float(values[key])
    except (KeyError, ValueError, TypeError) as exc:
        raise RainfallValidationError("invalid numeric rainfall record") from exc
    flags = row.get("quality_flags", row.get("quality_flag", ()))
    values["quality_flags"] = tuple(filter(None, flags.split(";"))) if isinstance(flags, str) else tuple(flags)
    values["extra"] = {key: value for key, value in row.items() if key not in values}
    record = RainfallRecord(**values)
    if bbox and not (bbox["min_lat"] <= record.latitude <= bbox["max_lat"]
                     and bbox["min_lon"] <= record.longitude <= bbox["max_lon"]):
        raise RainfallValidationError("rainfall coordinate lies outside the canonical study area")
    return record


def validate_records(records: Iterable[RainfallRecord], *, bbox: dict | None = None) -> list[RainfallRecord]:
    result = list(records)
    seen = set()
    for record in result:
        if bbox:
            normalize_record(record.as_dict(), bbox=bbox)
        native_center = (record.geometry or {}).get("center", (record.longitude, record.latitude))
        key = (record.source, record.product, record.timestamp_utc or record.reported_date,
               tuple(native_center), record.station_id)
        if key in seen:
            raise RainfallValidationError(f"duplicate rainfall record: {key}")
        seen.add(key)
    return result


def read_normalized_csv(path: Path, *, bbox: dict | None = None, source: str | None = None) -> list[RainfallRecord]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return validate_records(normalize_record({"source_file": relative_path(path), **row},
                                    bbox=bbox, source=source) for row in csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise RainfallValidationError(f"cannot read rainfall CSV {path}: {exc}") from exc
