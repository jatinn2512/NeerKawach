"""Deterministic quantitative-source selection with explicit fallback provenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings

from .registry import load_registry


ROOT = Path(__file__).resolve().parents[3]


def _matching_files(directory: object, pattern: object = None) -> list[Path]:
    if not isinstance(directory, str):
        return []
    root = ROOT / directory
    if not root.exists():
        return []
    if isinstance(pattern, str):
        return [path for path in root.glob(pattern) if path.is_file()]
    return [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".csv", ".json", ".tif", ".tiff", ".h5", ".hdf5", ".nc", ".grd"}]


def _files_for(source_id: str, config: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    processed = _matching_files(config.get("processed_directory"), config.get("processed_file_pattern"))
    raw = _matching_files(config.get("raw_directory"), config.get("raw_file_pattern"))
    return raw, processed


def _source_status(source_id: str, config: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    enabled = bool(config.get("enabled", False))
    raw_files, processed_files = _files_for(source_id, config)
    files = raw_files + processed_files
    if source_id == "dwr_qpe":
        available, status, reason = False, "reserved", "authorized IMD DWR access is not configured"
    elif source_id == "open_meteo_precipitation_forecast":
        available, status, reason = bool(settings.open_meteo_enabled), ("available" if settings.open_meteo_enabled else "disabled"), "public source configured" if settings.open_meteo_enabled else "disabled by configuration"
    elif source_id == "rainviewer_radar_observations":
        available, status, reason = bool(settings.rainviewer_enabled), ("available" if settings.rainviewer_enabled else "disabled"), "radar observation metadata configured" if settings.rainviewer_enabled else "disabled by configuration"
    elif processed_files:
        available, status, reason = True, "available", f"{len(processed_files)} normalized source file(s) found"
    elif raw_files:
        available, status, reason = True, "available_raw_unprocessed", f"{len(raw_files)} raw source file(s) found; normalization is required"
    else:
        available, status, reason = False, ("configured" if enabled else "disabled"), "no local source file is available"
    usable = bool(processed_files) if source_id not in {"open_meteo_precipitation_forecast", "rainviewer_radar_observations", "dwr_qpe"} else available
    return {"source_id": source_id, "name": config.get("name"), "provider": config.get("provider"), "product": config.get("product"), "role": config.get("role"), "enabled": enabled, "available": available, "usable": usable, "status": status, "reason": reason, "historical_available": config.get("historical_available", True), "historical_coverage_start_utc": config.get("historical_coverage_start_utc"), "historical_coverage_end_utc": config.get("historical_coverage_end_utc"), "raw_file_count": len(raw_files), "processed_file_count": len(processed_files), "local_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in files]}


def source_status() -> list[dict[str, Any]]:
    registry = load_registry()
    return [_source_status(source_id, config) for source_id, config in registry["sources"].items()]


def resolve_quantitative_source(requested: str | None = None, mode: str = "historical", start_utc: str | None = None, end_utc: str | None = None) -> dict[str, Any]:
    registry = load_registry()
    priority_key = "current_forecast_priority" if mode in {"current", "forecast"} else "default_quantitative_priority"
    configured_priority = list(registry[priority_key])
    if requested:
        priority = [requested, *[source_id for source_id in configured_priority if source_id != requested]]
    else:
        priority = configured_priority
    source_requested = requested or "auto"
    statuses = {item["source_id"]: item for item in source_status()}
    fallback_reasons: list[str] = []
    for source_id in priority:
        item = statuses.get(source_id)
        if item and item["usable"]:
            if mode == "historical" and not item.get("historical_available", True):
                fallback_reasons.append(f"{source_id}: source is not a historical dataset")
                continue
            coverage_start = item.get("historical_coverage_start_utc")
            coverage_end = item.get("historical_coverage_end_utc")
            if mode == "historical" and start_utc and end_utc and coverage_start and coverage_end and (start_utc < coverage_start or end_utc > coverage_end):
                fallback_reasons.append(f"{source_id}: requested period is outside {coverage_start} to {coverage_end}")
                continue
            substituted = requested is not None and source_id != requested
            return {"mode": mode, "source_requested": source_requested, "source_used": source_id, "fallback": substituted, "fallback_reason": "; ".join(fallback_reasons) if substituted else None, "priority": priority, "status": item}
        if item:
            fallback_reasons.append(f"{source_id}: {item['reason']}")
    return {"mode": mode, "source_requested": source_requested, "source_used": None, "fallback": False, "fallback_reason": "; ".join(fallback_reasons) or "no quantitative rainfall source is configured", "priority": priority, "status": None}
