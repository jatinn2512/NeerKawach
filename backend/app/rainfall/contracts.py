"""Validated internal rainfall records.

The contract preserves station records as points and does not resample one
provider into another provider's spatial resolution.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class RainfallValidationError(ValueError):
    """Raised when normalized rainfall data cannot be trusted."""


@dataclass(frozen=True)
class RainfallRecord:
    timestamp_utc: str
    latitude: float
    longitude: float
    rainfall_mm: float
    source: str
    product: str | None = None
    rainfall_rate_mm_h: float | None = None
    spatial_resolution: str | None = None
    units: str = "mm"
    quality_flags: tuple[str, ...] = ()
    observed: bool = False
    forecast: bool = False
    fallback: bool = False
    station_id: str | None = None
    mode: str | None = None
    extra: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "timestamp": self.timestamp_utc,
            "lat": self.latitude,
            "lon": self.longitude,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "rainfall_mm": self.rainfall_mm,
            "source": self.source,
            "product": self.product,
            "source_product": self.product,
            "rainfall_rate_mm_h": self.rainfall_rate_mm_h,
            "rainfall_rate_mm_per_hr": self.rainfall_rate_mm_h,
            "spatial_resolution": self.spatial_resolution,
            "resolution_m": self.spatial_resolution,
            "units": self.units,
            "quality_flags": list(self.quality_flags),
            "quality_flag": ";".join(self.quality_flags),
            "observed": self.observed,
            "is_observed": self.observed,
            "forecast": self.forecast,
            "is_forecast": self.forecast,
            "fallback": self.fallback,
            "is_fallback": self.fallback,
            "station_id": self.station_id,
            "mode": self.mode or ("forecast" if self.forecast else "observed" if self.observed else "unknown"),
        }


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RainfallValidationError(f"timestamp_utc must be a non-empty ISO-8601 string: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RainfallValidationError(f"invalid timestamp_utc: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RainfallValidationError("timestamp_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def normalize_record(row: dict[str, Any], *, source: str | None = None, bbox: dict[str, float] | None = None) -> RainfallRecord:
    timestamp = row.get("timestamp_utc", row.get("timestamp"))
    record_source = source or row.get("source")
    try:
        latitude = float(row["latitude"] if "latitude" in row else row["lat"])
        longitude = float(row["longitude"] if "longitude" in row else row["lon"])
        rainfall = float(row["rainfall_mm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RainfallValidationError("rainfall record requires latitude, longitude, and rainfall_mm") from exc
    if not isinstance(record_source, str) or not record_source.strip():
        raise RainfallValidationError("rainfall record requires a source")
    if not all(math.isfinite(value) for value in (latitude, longitude, rainfall)):
        raise RainfallValidationError("coordinates and rainfall_mm must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise RainfallValidationError("coordinates are outside geographic bounds")
    if rainfall < 0:
        raise RainfallValidationError("rainfall_mm cannot be negative")
    if bbox and not (bbox["min_lat"] <= latitude <= bbox["max_lat"] and bbox["min_lon"] <= longitude <= bbox["max_lon"]):
        raise RainfallValidationError("rainfall coordinate lies outside the canonical study area")
    rate = row.get("rainfall_rate_mm_h", row.get("rainfall_rate_mm_per_hr"))
    if rate is not None:
        try:
            rate = float(rate)
        except (TypeError, ValueError) as exc:
            raise RainfallValidationError("rainfall_rate_mm_h must be numeric") from exc
        if not math.isfinite(rate) or rate < 0:
            raise RainfallValidationError("rainfall_rate_mm_h must be finite and non-negative")
    flags = row.get("quality_flags", row.get("quality_flag", ()))
    if isinstance(flags, str):
        flags = tuple(flag for flag in flags.split(";") if flag)
    elif isinstance(flags, list | tuple):
        flags = tuple(str(flag) for flag in flags)
    else:
        flags = ()
    return RainfallRecord(
        timestamp_utc=_timestamp(timestamp), latitude=latitude, longitude=longitude,
        rainfall_mm=rainfall, source=record_source.strip(), product=row.get("product", row.get("source_product")),
        rainfall_rate_mm_h=rate, spatial_resolution=row.get("spatial_resolution", row.get("resolution_m")),
        units=str(row.get("units", "mm")), quality_flags=flags,
        observed=_bool(row.get("observed", row.get("is_observed", False))), forecast=_bool(row.get("forecast", row.get("is_forecast", False))),
        fallback=_bool(row.get("fallback", row.get("is_fallback", False))), station_id=row.get("station_id"), mode=row.get("mode"),
        extra={key: value for key, value in row.items() if key not in {"timestamp", "timestamp_utc", "latitude", "longitude", "rainfall_mm", "source", "product", "rainfall_rate_mm_h", "spatial_resolution", "units", "quality_flags", "observed", "forecast", "fallback", "station_id"}},
    )


def validate_records(records: Iterable[RainfallRecord], *, bbox: dict[str, float] | None = None) -> list[RainfallRecord]:
    result = list(records)
    seen: set[tuple[str, float, float, str | None]] = set()
    for record in result:
        normalize_record(record.as_dict(), bbox=bbox)
        key = (record.timestamp_utc, record.latitude, record.longitude, record.station_id)
        if key in seen:
            raise RainfallValidationError(f"duplicate rainfall record: {key}")
        seen.add(key)
    return result


def read_normalized_csv(path: Path, *, bbox: dict[str, float] | None = None, source: str | None = None) -> list[RainfallRecord]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise RainfallValidationError(f"cannot read rainfall CSV {path}: {exc}") from exc
    return validate_records((normalize_record(row, bbox=bbox, source=source) for row in rows), bbox=bbox)
