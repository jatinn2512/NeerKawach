"""Mock safer-route endpoint."""

from fastapi import APIRouter

from app.schemas import SaferRouteResponse

router = APIRouter(prefix="/route", tags=["route"])


@router.get("/safer", response_model=SaferRouteResponse)
def get_safer_route() -> SaferRouteResponse:
    """Return a sample route; no road graph or flood avoidance is performed."""

    return SaferRouteResponse(
        message="Sample safer route only; real routing is not implemented.",
        route_id="sample-route-001",
        total_distance_m=1_200,
        estimated_duration_minutes=6,
        segments=[
            {"segment_id": "sample-segment-001", "road_name": "Demo Road", "status": "safer-mock"}
        ],
    )
