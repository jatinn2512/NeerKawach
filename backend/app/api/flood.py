"""Mock flood-map and flood-risk endpoints."""

from fastapi import APIRouter, Query

from app.schemas import FloodMapResponse, FloodRiskResponse

router = APIRouter(prefix="/flood", tags=["flood"])


@router.get("/map", response_model=FloodMapResponse)
def get_flood_map(
    horizon_hours: float = Query(default=0.0, ge=0.0, le=3.0),
) -> FloodMapResponse:
    """Return a clearly labelled sample map payload for frontend integration."""

    return FloodMapResponse(
        message="Sample flood map only; no real flood prediction is performed.",
        horizon_hours=horizon_hours,
        layers=[
            {
                "layer_id": "sample-ponding",
                "name": "Sample ponding areas",
                "source": "mock",
                "description": "Placeholder geometry for future model output.",
                "features": [],
            }
        ],
    )


@router.get("/risk", response_model=FloodRiskResponse)
def get_flood_risk() -> FloodRiskResponse:
    """Return sample risk alerts; this endpoint does not calculate risk."""

    return FloodRiskResponse(
        message="Sample risk alerts only; no real flood-risk calculation is performed.",
        alerts=[
            {
                "alert_id": "sample-alert-001",
                "area": "Demo ward",
                "risk_level": "moderate",
                "description": "Placeholder alert for frontend integration.",
            }
        ],
    )
