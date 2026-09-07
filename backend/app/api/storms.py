"""Mock storm-run endpoint."""

from fastapi import APIRouter, Depends

from app.auth import require_roles
from app.schemas import MockUser, StormRunRequest, StormRunResponse

router = APIRouter(prefix="/storms", tags=["storms"])


@router.post("/run", response_model=StormRunResponse)
def run_mock_storm(
    request: StormRunRequest,
    user: MockUser = Depends(require_roles("admin", "operator")),
) -> StormRunResponse:
    """Accept validated demo input without running SWMM or flood simulation."""

    return StormRunResponse(
        message="Mock storm run accepted; no SWMM or flood simulation was executed.",
        run_id="mock-run-001",
        storm_name=request.storm_name,
        accepted_rainfall_mm=request.rainfall_mm,
        duration_minutes=request.duration_minutes,
        requested_by=user,
    )
