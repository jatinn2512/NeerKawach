"""Read-only P9 rainfall status and normalized-data service."""

from __future__ import annotations

from datetime import date, datetime
from itertools import groupby
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.rainfall.contracts import RainfallSeries, read_normalized_csv, utc_label, validate_records
from app.rainfall.providers.imd import ImdStationProvider, daily_metadata_path, read_daily_csv, read_daily_grid
from app.rainfall.providers.mosdac import MosdacProvider
from app.rainfall_sources import OPEN_METEO_SOURCE, OpenMeteoClient, RainfallSourceError, relative_path, utc_now
from app.rainfall.registry import load_registry
from app.rainfall.resolver import resolve_quantitative_source, source_files, source_status


ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data" / "rainfall"


def status(mode: str = "historical", requested_source: str | None = None) -> dict[str, Any]:
    sources = source_status()
    resolution = resolve_quantitative_source(requested=requested_source, mode=mode, statuses=sources)
    selected = resolution.get("status") or {}
    return {"mode": mode, "study_area": "config/study_area.json", "quantitative_priority": resolution["priority"], "source_requested": resolution.get("source_requested"), "source_used": resolution["source_used"], "source_name": selected.get("name"), "source_role": selected.get("role"), "fallback": resolution["fallback"], "fallback_reason": resolution["fallback_reason"], "sources": sources}


def metadata(source_id: str | None = None) -> dict[str, Any]:
    registry = load_registry()["sources"]
    if source_id is None:
        return {"sources": [{"source_id": key, **value} for key, value in registry.items()]}
    if source_id not in registry:
        raise HTTPException(status_code=404, detail={"error": "invalid_source", "message": "The requested rainfall source is not registered."})
    return {"source_id": source_id, **registry[source_id]}


def load_series(source: str, config: dict, as_of: datetime, current: bool = False) -> tuple[RainfallSeries, list[Path]]:
    raw, processed = source_files(config)
    if source == OPEN_METEO_SOURCE:
        series = OpenMeteoClient.read_archive(raw, processed, DATA_ROOT / "metadata", as_of=as_of, current=current)
        captures = sorted(series.captures, key=lambda c: datetime.fromisoformat(c["retrieved_at_utc"]))
        return series, [Path(c["processed_file"] or c["raw_file"]) for c in captures]
    if source == "mosdac_insat3dr" and processed:
        path = processed[-1]
        series = MosdacProvider(path.parent).read_subset(path, ROOT / config["metadata_file"])
        return series, [path]
    records, gaps, files = [], [], []
    if source == "imd_ncmrwf_gpm_merged_daily":
        native_products = set()
        for path in raw:
            sidecar = daily_metadata_path(path, DATA_ROOT / "metadata")
            bbox = json.loads((ROOT / "config/study_area.json").read_text(encoding="utf-8"))["bbox"]
            series = read_daily_grid(path, path.parent / "imd_gpm_template.ctl", sidecar, bbox)
            records.extend(series.records)
            files.append(path)
            native_products.add(sidecar.stem)
        for path in processed:
            if path.stem not in native_products:
                records.extend(read_daily_csv(path, DATA_ROOT / "metadata" / (path.stem + ".json")).records)
                files.append(path)
    else:
        if source == "arg_aws":
            for path in raw:
                if path.match(config["statement_pattern"]):
                    series = ImdStationProvider(path.parent).read_statement(path)
                    records.extend(series.records)
                    gaps.extend(series.missing_labels)
                    files.append(path)
        for path in processed:
            records.extend(read_normalized_csv(path, source=source))
            files.append(path)
    return RainfallSeries(validate_records(records), gaps), files


def _coverage(series, start, end, boundary):
    """Evaluate a query against source labels. A gap's neighbours are observations."""
    present = {boundary(r.timestamp_utc or r.reported_date) for r in series.records}
    absent = {boundary(label) for label in series.missing_labels} - present
    timeline = sorted(present | absent)
    outside = (end is not None and end < timeline[0]) or (start is not None and start > timeline[-1])
    extends = (start is not None and start < timeline[0]) or (end is not None and end > timeline[-1])
    gaps = []
    for missing, group in groupby(enumerate(timeline), key=lambda item: item[1] in absent):
        if not missing:
            continue
        run = list(group)
        left, right = run[0][0], run[-1][0]
        before = timeline[left-1] if left else None
        after = timeline[right+1] if right+1 < len(timeline) else None
        if ((before is None or end is None or end > before)
                and (after is None or start is None or start < after) and not outside):
            gaps.append({"first_missing_label": run[0][1].isoformat(), "last_missing_label": run[-1][1].isoformat(),
                         "before_label": before.isoformat() if before else None,
                         "after_label": after.isoformat() if after else None, "count": len(run)})
    return {"first_available_label": min(present).isoformat(), "last_available_label": max(present).isoformat(),
            "outside_coverage": outside, "extends_outside_coverage": extends, "intersecting_gaps": gaps}


def timeseries(source_id: str | None = None, start_utc: str | None = None, end_utc: str | None = None,
               mode: str = "historical") -> dict[str, Any]:
    registry = load_registry()["sources"]
    if source_id is not None and source_id not in registry:
        raise HTTPException(status_code=404, detail={"error": "invalid_source", "message": "Unknown rainfall source."})
    now = utc_now()
    live = mode in {"current", "forecast"}
    if source_id is None:
        try:
            start_utc = utc_label(start_utc) if start_utc else None
            end_utc = utc_label(end_utc) if end_utc else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": "invalid_period", "message": str(exc)}) from exc
    resolution = resolve_quantitative_source(requested=source_id, mode=mode, start_utc=start_utc, end_utc=end_utc,
                                            statuses=source_status(now))
    selected = resolution["source_used"]
    if not selected or (source_id and selected != source_id):
        raise HTTPException(status_code=503, detail={"error": "rainfall_unavailable", "source": source_id,
                            "message": resolution["fallback_reason"] or "No eligible local rainfall records."})
    try:
        series, paths = load_series(selected, registry[selected], now, current=live)
    except (OSError, KeyError, ValueError, TypeError, RainfallSourceError) as exc:
        raise HTTPException(status_code=503, detail={"error": "invalid_rainfall", "message": str(exc)}) from exc
    if not series.records:
        raise HTTPException(status_code=503, detail={"error": "rainfall_unavailable", "source": selected})
    records = series.records
    missing = series.missing_labels
    date_only = all(r.timestamp_utc is None for r in records)
    def boundary(value):
        return date.fromisoformat(value) if date_only else datetime.fromisoformat(utc_label(value))
    start = end = None
    if start_utc or end_utc:
        try:
            start = boundary(start_utc) if start_utc else None
            end = boundary(end_utc) if end_utc else None
            if start and end and start > end:
                raise ValueError("reversed period")
            def within(label):
                instant = boundary(label)
                return (start is None or start <= instant) and (end is None or instant <= end)
            records = [r for r in records if within(r.timestamp_utc or r.reported_date)]
            missing = [label for label in missing if within(label)]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": "invalid_period",
                                "message": "Use reported dates for daily stations and zoned timestamps for UTC series."}) from exc
    coverage = _coverage(series, start, end, boundary)
    gap = bool(coverage["intersecting_gaps"])
    if not records:
        error = ("outside_coverage" if coverage["outside_coverage"] else
                 "coverage_gap" if gap else "no_observation_labels")
        raise HTTPException(status_code=404, detail={"error": error, "source": selected,
                            "missing_labels": missing, "coverage": coverage})
    has_valid = any(not r.missing for r in records)
    partial = gap or coverage["extends_outside_coverage"] or any(r.missing for r in records)
    coverage_status = "missing_data" if not has_valid else "partial" if partial else "available"
    return {"coverage_status": coverage_status, "coverage": coverage,
            "mode": mode, "source": selected, "source_product": series.records[0].product,
            "source_role": registry[selected]["role"], "file": relative_path(paths[-1]),
            "files": [relative_path(p) for p in paths], "start_utc": start_utc, "end_utc": end_utc,
            "missing_labels": missing, "captures": series.captures, "records": [r.as_dict() for r in records]}


def nowcast_status() -> dict[str, Any]:
    return {"available": False, "mode": "reserved", "source": None, "future_radar_nowcast": False, "message": "No quantitative 0–3 hour nowcast provider is currently configured. RainViewer is recent/past radar observation only; Open-Meteo is model forecast."}


def current_status() -> dict[str, Any]:
    return status(mode="current")
