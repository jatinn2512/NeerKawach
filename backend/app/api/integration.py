"""P9 API endpoints exposing validated, precomputed FloodOps products."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import products
from app.services.routing import route as route_p8


router = APIRouter(prefix="/api", tags=["P9 decision support"])


class RouteRequest(BaseModel):
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)
    simulation_timestamp: str = Field(description="Exact ISO-8601 timestamp present in validated P7/P8 inputs.")
    routing_mode: Literal["baseline", "flood-aware"]


@router.get("/status", summary="Backend and validated-product status")
def status() -> dict[str, Any]:
    area = products.study_area()
    summary_path = products.P7_ROOT / "metrics" / "p7_summary.json"
    routing_ready = products.routing_available()
    return {"api_status": "ok", "project_name": get_settings().app_name, "study_area": area.get("name"),
            "available_data_products": {"p6": (products.P6_ROOT / "results" / "coupling_summary.json").exists(), "p7": summary_path.exists(), "p8": routing_ready},
            "routing_capability": "P8 validated routing" if routing_ready else "unavailable", "latest_runs": products.discover_runs()}


@router.get("/study-area", summary="Canonical study-area metadata")
def get_study_area() -> dict[str, Any]:
    return products.study_area()


@router.get("/flood/summary", summary="Validated P7 flood summary")
def flood_summary() -> dict[str, Any]:
    return products.p7_summary()


@router.get("/flood/timeseries", summary="Validated P7 flood metrics time series")
def flood_timeseries(timestamp: Annotated[str | None, Query(description="Exact validated P7 timestamp.")] = None) -> dict[str, Any]:
    if timestamp is not None:
        products.require_timestamp(timestamp)
    rows = products.p7_timeseries()
    return {"timestamp": timestamp, "units": {"depth": "metres", "area": "square metres"}, "rows": [row for row in rows if timestamp is None or row.get("timestamp") == timestamp]}


@router.get("/flood/extent", summary="Validated P7 flood-extent GeoJSON")
def flood_extent(timestamp: Annotated[str | None, Query(description="Exact P7 timestamp; omit for maximum-over-time extent.")] = None) -> dict[str, Any]:
    return products.p7_extent(timestamp)


@router.get("/flood/max-depth", summary="Validated P7 maximum-depth metric")
def flood_max_depth() -> dict[str, Any]:
    summary = products.p7_summary()
    return {"maximum_flood_depth": summary.get("maximum_flood_depth"), "units": {"depth": "metres"}, "source_phase": summary.get("source_phase"), "timestamps": summary.get("timestamps")}


@router.get("/roads/impact", summary="Validated P7 timestamped road impacts")
def roads_impact(timestamp: str | None = None, road_id: str | None = None) -> dict[str, Any]:
    if timestamp is not None:
        products.require_timestamp(timestamp)
    rows = products.p7_road_impacts()
    known_ids = {row.get("road_id") for row in rows}
    if road_id is not None and road_id not in known_ids:
        raise products.invalid("road_id", road_id)
    filtered = [row for row in rows if (timestamp is None or row.get("timestamp") == timestamp) and (road_id is None or row.get("road_id") == road_id)]
    return {"timestamp": timestamp, "road_id": road_id, "units": {"maximum_flood_depth": "metres"}, "rows": filtered}


@router.post("/routes", summary="Route using the existing P8 implementation")
def routes(request: RouteRequest) -> dict[str, Any]:
    products.require_timestamp(request.simulation_timestamp)
    return route_p8((request.origin_longitude, request.origin_latitude), (request.destination_longitude, request.destination_latitude), request.simulation_timestamp, request.routing_mode)


@router.get("/runs", summary="Discover validated P6, P7, and P8 products")
def runs() -> dict[str, Any]:
    return {"runs": products.discover_runs()}


@router.get("/rainfall/sources", summary="Stored rainfall-source metadata; no live requests")
def rainfall_sources() -> dict[str, Any]:
    return {"sources": products.rainfall_sources()}
