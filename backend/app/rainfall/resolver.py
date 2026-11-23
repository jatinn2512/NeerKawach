"""Source-specific local discovery, availability and quantitative-source selection."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.rainfall.providers.imd import daily_metadata_path
from app.rainfall_sources import OPEN_METEO_SOURCE, OpenMeteoClient, RainfallSourceError, utc_now
from .registry import load_registry

ROOT = Path(__file__).resolve().parents[3]


def _matching_files(directory: str | None, pattern: str) -> list[Path]:
    if not directory:
        return []
    return sorted(p for p in (ROOT / directory).glob(pattern) if p.is_file())


def source_files(config: dict) -> tuple[list[Path], list[Path]]:
    raw = _matching_files(config.get("raw_directory"), config.get("raw_file_pattern", "**/*"))
    raw = [p for p in raw if p.suffix.lower() in {".csv", ".json", ".tif", ".tiff", ".h5", ".hdf5", ".nc", ".grd"}]
    raw.extend(_matching_files(config.get("statement_directory"), config.get("statement_pattern", "*.csv")))
    processed = _matching_files(config.get("processed_directory"), config.get("processed_file_pattern", "**/*.csv"))
    return raw, processed


def _source_status(source_id: str, config: dict[str, Any], as_of: datetime) -> dict:
    raw, processed = source_files(config)
    enabled = bool(config.get("enabled"))
    status = "available" if processed else "available_raw_unprocessed" if raw else "unavailable"
    usable = bool(processed)
    reason = {"available": "normalized records found", "available_raw_unprocessed": "raw data requires a reader",
              "unavailable": "no local rainfall records found"}[status]
    current = False
    detail = {}
    if source_id == OPEN_METEO_SOURCE:
        enabled = enabled and get_settings().open_meteo_enabled
        try:
            archive = OpenMeteoClient.read_archive(raw, processed, ROOT / "data/rainfall/metadata", as_of=as_of)
            usable = bool(archive.records)
            current = any(c["current_usable"] for c in archive.captures)
            if usable:
                status = "available" if current else "stale" if all(c["expired"] for c in archive.captures) else "unavailable_as_of"
                reason = "stored forecast validity checked against the current UTC time"
            detail = {"capture_count": len(archive.captures),
                      "distinct_series_count": len({c["series_id"] for c in archive.captures}),
                      "last_valid_utc": max((c["last_valid_utc"] for c in archive.captures), default=None)}
        except (OSError, ValueError, TypeError, KeyError, RainfallSourceError) as exc:
            status, usable, reason = "invalid", False, str(exc)
    elif source_id == "arg_aws" and any(p.match(config["statement_pattern"]) for p in raw):
        status, usable, reason = "available", True, "historical daily station statement for regional comparison"
    elif source_id == "imd_ncmrwf_gpm_merged_daily" and raw:
        try:
            usable = all((p.parent / "imd_gpm_template.ctl").is_file() and
                         daily_metadata_path(p, ROOT / "data/rainfall/metadata").is_file() for p in raw)
        except ValueError:
            usable = False
        status = "available" if usable else "incomplete"
        reason = "local daily grid, control and acquisition metadata required"
    elif source_id == "dwr_qpe":
        status, usable, reason = "reserved", False, "authorized IMD DWR access is not configured"
    elif source_id == "rainviewer_radar_observations":
        enabled = enabled and get_settings().rainviewer_enabled
        usable, reason = False, "radar timeline references only"
    if not enabled and status != "reserved":
        status, usable, current, reason = "disabled", False, False, "disabled by configuration"
    return {"source_id": source_id, "name": config.get("name"), "provider": config.get("provider"),
            "product": config.get("product"), "role": config.get("role"), "enabled": enabled,
            "available": enabled and bool(raw or processed) and status != "invalid",
            "usable": usable, "current_usable": current, "status": status, "reason": reason, **detail,
            "historical_available": config.get("historical_available", True),
            "historical_coverage_start_utc": config.get("historical_coverage_start_utc"),
            "historical_coverage_end_utc": config.get("historical_coverage_end_utc"),
            "raw_file_count": len(raw), "processed_file_count": len(processed),
            "local_files": [p.relative_to(ROOT).as_posix() for p in raw + processed]}


def source_status(as_of: datetime | None = None) -> list[dict[str, Any]]:
    now = as_of or utc_now()
    return [_source_status(key, config, now) for key, config in load_registry()["sources"].items()]


def resolve_quantitative_source(requested: str | None = None, mode: str = "historical",
                                start_utc: str | None = None, end_utc: str | None = None,
                                *, statuses: list[dict] | None = None) -> dict:
    registry = load_registry()
    live = mode in {"current", "forecast"}
    priority = list(registry["current_forecast_priority" if live else "default_quantitative_priority"])
    if requested:
        # Preserve the existing explicit DWR fallback contract. Other named sources are exact requests.
        priority = [requested] + ([s for s in priority if s != requested] if requested == "dwr_qpe" else [])
    by_id = {item["source_id"]: item for item in (source_status() if statuses is None else statuses)}
    reasons = []
    for key in priority:
        item = by_id.get(key)
        if not item or not item["usable"] or (live and not item["current_usable"]):
            reasons.append(f"{key}: {item['status'] if item else 'unknown'}")
            continue
        if not live and not requested:
            # Regional daily statements must never silently replace a catchment forcing source.
            if not item["historical_available"] or key == "arg_aws":
                continue
            first, last = item["historical_coverage_start_utc"], item["historical_coverage_end_utc"]
            if ((first and end_utc and datetime.fromisoformat(end_utc) < datetime.fromisoformat(first))
                    or (last and start_utc and datetime.fromisoformat(start_utc) > datetime.fromisoformat(last))):
                continue
        substituted = bool(requested and key != requested)
        return {"mode": mode, "source_requested": requested or "auto", "source_used": key,
                "fallback": substituted, "fallback_reason": "; ".join(reasons) if substituted else None,
                "priority": priority, "status": item}
    return {"mode": mode, "source_requested": requested or "auto", "source_used": None, "fallback": False,
            "fallback_reason": "; ".join(reasons) or "no eligible local rainfall source", "priority": priority, "status": None}
