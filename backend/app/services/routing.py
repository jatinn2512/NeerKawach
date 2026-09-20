"""Thin, read-only bridge to the locked P8 routing implementation."""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.services.products import ROOT


@lru_cache
def p8_module() -> Any:
    path = ROOT / "scripts" / "data" / "route_flood_safe.py"
    if not path.exists():
        raise HTTPException(status_code=503, detail={"error": "product_unavailable", "message": "P8 routing implementation is unavailable."})
    spec = importlib.util.spec_from_file_location("floodops_p8_routing", path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=503, detail={"error": "product_unavailable", "message": "P8 routing implementation cannot be loaded."})
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def route(origin: tuple[float, float], destination: tuple[float, float], timestamp: str, mode: str) -> dict[str, Any]:
    try:
        engine = p8_module().create_engine()
        result = engine.route(origin, destination, timestamp)
        selected = result["baseline"] if mode == "baseline" else result["flood_aware"]
        return {
            "status": result["status"], "routing_mode": mode, "route_timestamp": result["timestamp"],
            "total_distance_m": selected["distance_m"], "route_cost": selected["route_cost"],
            "maximum_flood_depth_m": selected["maximum_depth_m"], "affected_segments": selected["affected_segments"],
            "avoided_flooded_segments": result["avoided_flooded_segments"], "geometry": engine.to_geojson(result),
            "source_phase": "P8",
        }
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail={"error": "product_unavailable", "message": "Validated P8 routing inputs are not available."}) from exc
    except ValueError as exc:
        message = str(exc)
        status = 404 if "Timestamp is not present" in message else 422
        raise HTTPException(status_code=status, detail={"error": "routing_failed", "message": message}) from exc
