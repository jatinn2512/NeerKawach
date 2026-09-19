"""Public rainfall-source clients for the locked Bellandur study area.

Open-Meteo is model-derived precipitation. RainViewer is a radar observation
timeline and tile-reference source. Neither adapter is DWR and RainViewer
imagery is deliberately not converted into quantitative rainfall values.
"""

from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


ROOT = Path(__file__).resolve().parents[2]
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"
RAINFALL_ROOT = ROOT / "data" / "rainfall"
CANONICAL_SCHEMA = ("timestamp", "latitude", "longitude", "rainfall_mm", "source")
OPEN_METEO_SOURCE = "open_meteo_precipitation_forecast"
RAINVIEWER_SOURCE = "rainviewer_radar_observations"
RAINVIEWER_ATTRIBUTION_URL = "https://www.rainviewer.com/"
RAINVIEWER_ATTRIBUTION_TEXT = "Weather data by RainViewer"


class RainfallSourceError(RuntimeError):
    """Raised when a public rainfall source cannot be safely ingested."""


def load_study_area() -> dict[str, Any]:
    try:
        area = json.loads(STUDY_AREA_PATH.read_text(encoding="utf-8"))
        bbox = area["bbox"]
        keys = ("min_lat", "min_lon", "max_lat", "max_lon")
        if any(key not in bbox for key in keys):
            raise ValueError("study-area bbox is incomplete")
        if not (bbox["min_lat"] < bbox["max_lat"] and bbox["min_lon"] < bbox["max_lon"]):
            raise ValueError("study-area bbox is not ordered")
        if area.get("crs") != "EPSG:4326":
            raise ValueError("rainfall sources require the canonical EPSG:4326 study area")
        return area
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RainfallSourceError(f"Could not load canonical study area from {STUDY_AREA_PATH}: {exc}") from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_source_timestamp(value: object, *, assume_timezone: timezone | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RainfallSourceError(f"Invalid source timestamp: {value!r}")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RainfallSourceError(f"Invalid source timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        if assume_timezone is None:
            raise RainfallSourceError(f"Source timestamp has no timezone: {value!r}")
        parsed = parsed.replace(tzinfo=assume_timezone)
    return timestamp_text(parsed)


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        # Test callers may use a temporary output root outside the repository.
        return path.as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class _JSONClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        retries: int = 2,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("rainfall HTTP timeout must be positive")
        if retries < 0:
            raise ValueError("rainfall HTTP retries cannot be negative")
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.http_client = http_client
        self.sleep = sleep

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        owns_client = self.http_client is None
        client = self.http_client or httpx.Client(timeout=self.timeout_seconds, follow_redirects=True)
        try:
            for attempt in range(self.retries + 1):
                try:
                    response = client.get(url, params=params, headers={"User-Agent": "FloodOps-rainfall/1.0"})
                    if response.status_code in {408, 425, 429} or response.status_code >= 500:
                        response.raise_for_status()
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise RainfallSourceError(f"Expected a JSON object from {url}")
                    return payload
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError, RainfallSourceError) as exc:
                    last_error = exc
                    retryable = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
                    if isinstance(exc, httpx.HTTPStatusError):
                        retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                    if isinstance(exc, (ValueError, RainfallSourceError)):
                        retryable = False
                    if attempt >= self.retries or not retryable:
                        break
                    self.sleep(0.25 * (2**attempt))
        finally:
            if owns_client:
                client.close()
        raise RainfallSourceError(f"Rainfall request failed after {self.retries + 1} attempt(s): {url}: {last_error}") from last_error


class OpenMeteoClient(_JSONClient):
    """Fetch hourly model precipitation for one deterministic source grid point."""

    def __init__(self, *, base_url: str = "https://api.open-meteo.com", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def request_for_area(area: dict[str, Any], forecast_days: int = 3) -> tuple[dict[str, Any], tuple[float, float]]:
        if not 1 <= forecast_days <= 16:
            raise ValueError("Open-Meteo forecast_days must be between 1 and 16")
        bbox = area["bbox"]
        # One centroid request avoids inventing a finer grid than the returned
        # model cell. The response's grid-cell coordinate is retained in rows.
        latitude = round((float(bbox["min_lat"]) + float(bbox["max_lat"])) / 2.0, 6)
        longitude = round((float(bbox["min_lon"]) + float(bbox["max_lon"])) / 2.0, 6)
        return {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation",
            "forecast_days": forecast_days,
            "timezone": "UTC",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        }, (latitude, longitude)

    def fetch(self, *, forecast_days: int = 3, output_root: Path = RAINFALL_ROOT, retrieved_at: datetime | None = None) -> dict[str, Any]:
        area = load_study_area()
        params, requested_coordinate = self.request_for_area(area, forecast_days)
        retrieved = retrieved_at or utc_now()
        run_id = retrieved.strftime("%Y%m%dT%H%M%SZ")
        raw_path = output_root / "raw" / "open_meteo" / f"open_meteo_{run_id}.json"
        processed_path = output_root / "processed" / f"open_meteo_{run_id}.csv"
        metadata_path = output_root / "metadata" / f"open_meteo_{run_id}.json"
        payload = self.get_json(f"{self.base_url}/v1/forecast", params)
        write_json(raw_path, payload)
        rows, response_metadata = self._normalize(payload, requested_coordinate)
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        with processed_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CANONICAL_SCHEMA))
            writer.writeheader()
            writer.writerows(rows)
        metadata = {
            "source": OPEN_METEO_SOURCE,
            "source_name": "Open-Meteo precipitation forecast",
            "source_type": "numerical_weather_model_forecast",
            "provider": "Open-Meteo",
            "endpoint": f"{self.base_url}/v1/forecast",
            "retrieved_at_utc": timestamp_text(retrieved),
            "requested_coordinates": {"latitude": requested_coordinate[0], "longitude": requested_coordinate[1]},
            "response_grid_coordinate": response_metadata["response_grid_coordinate"],
            "study_area": area["bbox"],
            "crs": "EPSG:4326",
            "spatial_resolution": "provider/model grid; returned grid-cell coordinate is preserved; no finer grid is implied",
            "temporal_resolution": "hourly",
            "units": "millimetres per hourly precipitation accumulation",
            "model_metadata": response_metadata["model_metadata"],
            "request_parameters": params,
            "response_metadata": response_metadata["response_metadata"],
            "schema": list(CANONICAL_SCHEMA),
            "record_count": len(rows),
            "raw_file": relative_path(raw_path),
            "processed_file": relative_path(processed_path),
            "limitations": ["Model forecast, not radar or DWR/QPE.", "The single centroid request represents the source model grid cell and is not a street-level rainfall field."],
        }
        write_json(metadata_path, metadata)
        metadata["metadata_file"] = relative_path(metadata_path)
        return metadata

    @staticmethod
    def _normalize(payload: dict[str, Any], requested_coordinate: tuple[float, float]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        hourly = payload.get("hourly")
        units = payload.get("hourly_units")
        if not isinstance(hourly, dict) or not isinstance(units, dict):
            raise RainfallSourceError("Open-Meteo response is missing hourly data or hourly_units")
        times = hourly.get("time")
        precipitation = hourly.get("precipitation")
        if not isinstance(times, list) or not isinstance(precipitation, list) or len(times) != len(precipitation) or not times:
            raise RainfallSourceError("Open-Meteo response has invalid time/precipitation arrays")
        if units.get("precipitation") != "mm":
            raise RainfallSourceError(f"Open-Meteo precipitation unit is not mm: {units.get('precipitation')!r}")
        response_lat = payload.get("latitude")
        response_lon = payload.get("longitude")
        if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (response_lat, response_lon)):
            raise RainfallSourceError("Open-Meteo response has invalid grid-cell coordinates")
        rows = []
        for source_time, value in zip(times, precipitation):
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise RainfallSourceError(f"Open-Meteo response has invalid precipitation value: {value!r}")
            rows.append({"timestamp": parse_source_timestamp(source_time, assume_timezone=timezone.utc), "latitude": float(response_lat), "longitude": float(response_lon), "rainfall_mm": float(value), "source": OPEN_METEO_SOURCE})
        return rows, {
            "response_grid_coordinate": {"latitude": float(response_lat), "longitude": float(response_lon)},
            "model_metadata": {"model_selection": "auto", **{key: payload.get(key) for key in ("model", "models", "generationtime_ms", "elevation", "timezone", "timezone_abbreviation") if key in payload}},
            "response_metadata": {key: payload.get(key) for key in ("latitude", "longitude", "elevation", "generationtime_ms", "utc_offset_seconds", "timezone", "timezone_abbreviation", "hourly_units") if key in payload},
            "requested_coordinate": {"latitude": requested_coordinate[0], "longitude": requested_coordinate[1]},
        }


class RainViewerClient(_JSONClient):
    """Fetch RainViewer's public past-radar timeline and target references."""

    def __init__(self, *, base_url: str = "https://api.rainviewer.com/public/weather-maps.json", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url

    def fetch(self, *, output_root: Path = RAINFALL_ROOT, retrieved_at: datetime | None = None) -> dict[str, Any]:
        area = load_study_area()
        retrieved = retrieved_at or utc_now()
        run_id = retrieved.strftime("%Y%m%dT%H%M%SZ")
        raw_path = output_root / "raw" / "rainviewer" / f"rainviewer_weather_maps_{run_id}.json"
        index_path = output_root / "metadata" / f"rainviewer_{run_id}.json"
        payload = self.get_json(self.base_url)
        write_json(raw_path, payload)
        radar = payload.get("radar") if isinstance(payload.get("radar"), dict) else {}
        past = radar.get("past", [])
        nowcast = radar.get("nowcast", [])
        if not isinstance(past, list) or not isinstance(nowcast, list):
            raise RainfallSourceError("RainViewer response has invalid radar past/nowcast arrays")
        host = payload.get("host")
        if not isinstance(host, str) or not host.startswith(("http://", "https://")):
            raise RainfallSourceError("RainViewer response has no valid tile host")
        bbox = area["bbox"]
        target = {"latitude": round((float(bbox["min_lat"]) + float(bbox["max_lat"])) / 2.0, 6), "longitude": round((float(bbox["min_lon"]) + float(bbox["max_lon"])) / 2.0, 6)}
        frames = [self._frame_reference(frame, host, target) for frame in past]
        generated = payload.get("generated")
        metadata = {
            "source": RAINVIEWER_SOURCE,
            "source_name": "RainViewer radar observations",
            "source_type": "radar_observation_timeline",
            "provider": "RainViewer",
            "endpoint": self.base_url,
            "retrieved_at_utc": timestamp_text(retrieved),
            "generated_at_utc": timestamp_text(datetime.fromtimestamp(float(generated), tz=timezone.utc)) if isinstance(generated, (int, float)) else None,
            "study_area": bbox,
            "crs": "EPSG:4326 for target coordinate references; tile imagery uses RainViewer web-map tiling",
            "target_coordinate": target,
            "past_frame_count": len(frames),
            "past_frames": frames,
            "nowcast_frames_received": len(nowcast),
            "future_nowcast_available": False,
            "future_nowcast_policy": "Future RainViewer radar nowcast is not used; the public future-nowcast service was discontinued on 2026-01-01.",
            "geographic_relevance": "Past timeline references are generated for the Bellandur coordinate; the timeline endpoint does not itself provide a station-level coverage assertion.",
            "quantitative_rainfall_available": False,
            "raw_file": relative_path(raw_path),
            "attribution": {"text": RAINVIEWER_ATTRIBUTION_TEXT, "url": RAINVIEWER_ATTRIBUTION_URL, "required_for_user_facing_visualization": True},
            "authentication_required": False,
            "limitations": ["Radar observation imagery/timeline only; no rainfall-mm normalization is performed.", "Past frames are typically available for about two hours at ten-minute intervals.", "Public API availability is best effort and has no SLA."],
        }
        write_json(index_path, metadata)
        metadata["metadata_file"] = relative_path(index_path)
        return metadata

    @staticmethod
    def _frame_reference(frame: Any, host: str, target: dict[str, float]) -> dict[str, Any]:
        if not isinstance(frame, dict) or not isinstance(frame.get("time"), (int, float)) or not isinstance(frame.get("path"), str):
            raise RainfallSourceError(f"RainViewer response has malformed radar frame: {frame!r}")
        path = frame["path"]
        tile_base = f"{host.rstrip('/')}{path}/512/7/{target['latitude']:.6f}/{target['longitude']:.6f}/2/1_0.png"
        coverage = f"{host.rstrip('/')}/v2/coverage/0/512/7/{target['latitude']:.6f}/{target['longitude']:.6f}/0/0_0.png"
        return {
            "frame_time_utc": timestamp_text(datetime.fromtimestamp(float(frame["time"]), tz=timezone.utc)),
            "frame_unix_time": int(frame["time"]),
            "path": path,
            "bellandur_tile_url": tile_base,
            "bellandur_coverage_reference_url": coverage,
            "imagery_downloaded": False,
            "rainfall_mm": None,
            "interpretation": "Radar image reference only; no quantitative rainfall conversion.",
        }
