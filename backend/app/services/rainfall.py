"""Read-only P9 rainfall status and normalized-data service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.rainfall.contracts import RainfallValidationError, read_normalized_csv
from app.rainfall.registry import load_registry
from app.rainfall.resolver import resolve_quantitative_source, source_status


ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data" / "rainfall"


def status(mode: str = "historical", requested_source: str | None = None) -> dict[str, Any]:
    resolution = resolve_quantitative_source(requested=requested_source, mode=mode)
    selected = resolution.get("status") or {}
    return {"mode": mode, "study_area": "config/study_area.json", "quantitative_priority": resolution["priority"], "source_requested": resolution.get("source_requested"), "source_used": resolution["source_used"], "source_name": selected.get("name"), "source_role": selected.get("role"), "fallback": resolution["fallback"], "fallback_reason": resolution["fallback_reason"], "sources": source_status()}


def metadata(source_id: str | None = None) -> dict[str, Any]:
    registry = load_registry()["sources"]
    if source_id is None:
        return {"sources": [{"source_id": key, **value} for key, value in registry.items()]}
    if source_id not in registry:
        raise HTTPException(status_code=404, detail={"error": "invalid_source", "message": "The requested rainfall source is not registered."})
    return {"source_id": source_id, **registry[source_id]}


def timeseries(source_id: str | None = None, start_utc: str | None = None, end_utc: str | None = None, mode: str = "historical") -> dict[str, Any]:
    resolution = resolve_quantitative_source(mode=mode, start_utc=start_utc, end_utc=end_utc)
    selected = source_id or resolution.get("source_used")
    if not selected:
        raise HTTPException(status_code=503, detail={"error": "rainfall_unavailable", "message": "No quantitative rainfall source is available."})
    if selected not in load_registry()["sources"]:
        raise HTTPException(status_code=404, detail={"error": "invalid_source", "message": "The requested rainfall source is not registered."})
    candidates: list[Path]
    if selected == "open_meteo_precipitation_forecast":
        candidates = sorted(DATA_ROOT.glob("processed/open_meteo_*.csv"))
    elif selected == "imd_ncmrwf_gpm_merged_daily":
        candidates = sorted(DATA_ROOT.glob("processed/imd_gpm_*.csv"))
    else:
        config = load_registry()["sources"][selected]
        processed = config.get("processed_directory")
        processed_root = ROOT / processed if isinstance(processed, str) else DATA_ROOT / "processed"
        pattern = config.get("processed_file_pattern")
        candidates = sorted(processed_root.glob(pattern)) if isinstance(pattern, str) else sorted(processed_root.glob(f"{selected}*.csv")) + sorted(processed_root.glob(f"**/{selected}*.csv"))
    if not candidates:
        raise HTTPException(status_code=503, detail={"error": "rainfall_unavailable", "message": f"No normalized rainfall file is available for {selected}."})
    path = candidates[-1]
    try:
        records = read_normalized_csv(path)
    except RainfallValidationError as exc:
        raise HTTPException(status_code=503, detail={"error": "invalid_rainfall", "message": str(exc)}) from exc
    if start_utc is not None or end_utc is not None:
        start = start_utc or ""
        end = end_utc or "\uffff"
        records = [record for record in records if start <= record.timestamp_utc <= end]
    return {"mode": mode, "source": selected, "source_product": load_registry()["sources"][selected].get("product"), "file": str(path.relative_to(ROOT)).replace("\\", "/"), "start_utc": start_utc, "end_utc": end_utc, "records": [record.as_dict() for record in records]}


def nowcast_status() -> dict[str, Any]:
    return {"available": False, "mode": "reserved", "source": None, "future_radar_nowcast": False, "message": "No quantitative 0–3 hour nowcast provider is currently configured. RainViewer is recent/past radar observation only; Open-Meteo is model forecast."}


def current_status() -> dict[str, Any]:
    return status(mode="current")
