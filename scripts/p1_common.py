"""Shared P1 helpers. This module deliberately has no geospatial dependencies."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"


def load_study_area() -> dict:
    with STUDY_AREA_PATH.open(encoding="utf-8") as handle:
        area = json.load(handle)
    bbox = area["bbox"]
    required = ("min_lat", "min_lon", "max_lat", "max_lon")
    if any(key not in bbox for key in required):
        raise ValueError("study_area.json bbox is incomplete")
    if not (bbox["min_lat"] < bbox["max_lat"] and bbox["min_lon"] < bbox["max_lon"]):
        raise ValueError("study_area.json bbox must be ordered south-west to north-east")
    if area.get("crs") != "EPSG:4326":
        raise ValueError("P1 acquisition scripts require the canonical EPSG:4326 study area")
    return area


def bbox_tuple(area: dict) -> tuple[float, float, float, float]:
    bbox = area["bbox"]
    return bbox["min_lat"], bbox["min_lon"], bbox["max_lat"], bbox["max_lon"]
