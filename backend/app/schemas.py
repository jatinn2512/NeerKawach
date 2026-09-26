"""Pydantic contracts for the initial Neer Kawach API foundation.

These models intentionally describe mock/sample payloads only. They are small
contracts that can be extended when real model outputs are introduced.
"""

from typing import Literal

from pydantic import BaseModel, Field


class MockUser(BaseModel):
    """Development-only user identity used by the mock auth dependency."""

    username: str
    role: Literal["admin", "operator", "viewer"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    message: str


class FloodMapLayer(BaseModel):
    layer_id: str
    name: str
    source: Literal["mock"]
    description: str
    features: list[dict[str, object]] = Field(default_factory=list)


class FloodMapResponse(BaseModel):
    status: Literal["mock"] = "mock"
    is_mock: Literal[True] = True
    message: str
    horizon_hours: float
    layers: list[FloodMapLayer]


class FloodRiskAlert(BaseModel):
    alert_id: str
    area: str
    risk_level: Literal["low", "moderate", "high"]
    description: str
    is_mock: Literal[True] = True


class FloodRiskResponse(BaseModel):
    status: Literal["mock"] = "mock"
    is_mock: Literal[True] = True
    message: str
    alerts: list[FloodRiskAlert]


class RouteSegment(BaseModel):
    segment_id: str
    road_name: str
    status: Literal["safer-mock"]


class SaferRouteResponse(BaseModel):
    status: Literal["mock"] = "mock"
    is_mock: Literal[True] = True
    message: str
    route_id: str
    total_distance_m: int
    estimated_duration_minutes: int
    segments: list[RouteSegment]


class DrainageNode(BaseModel):
    node_id: str
    name: str
    status: Literal["sample"]


class DrainageLink(BaseModel):
    link_id: str
    from_node: str
    to_node: str
    status: Literal["sample"]


class DrainageResponse(BaseModel):
    status: Literal["mock"] = "mock"
    is_mock: Literal[True] = True
    message: str
    nodes: list[DrainageNode]
    links: list[DrainageLink]


class StormRunRequest(BaseModel):
    storm_name: str = Field(default="demo-storm", min_length=1, max_length=100)
    rainfall_mm: float = Field(default=25.0, ge=0, le=500)
    duration_minutes: int = Field(default=60, ge=5, le=1_440)


class StormRunResponse(BaseModel):
    status: Literal["mock"] = "mock"
    is_mock: Literal[True] = True
    message: str
    run_id: str
    storm_name: str
    accepted_rainfall_mm: float
    duration_minutes: int
    requested_by: MockUser
