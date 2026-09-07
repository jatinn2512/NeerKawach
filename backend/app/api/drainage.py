"""Placeholder drainage-network endpoint."""

from fastapi import APIRouter

from app.schemas import DrainageResponse

router = APIRouter(prefix="/drainage", tags=["drainage"])


@router.get("", response_model=DrainageResponse)
def get_drainage_network() -> DrainageResponse:
    """Return a small sample network without hydraulic calculations."""

    return DrainageResponse(
        message="Sample drainage network only; no hydraulic calculation is performed.",
        nodes=[
            {"node_id": "sample-node-a", "name": "Demo inlet A", "status": "sample"},
            {"node_id": "sample-node-b", "name": "Demo outfall B", "status": "sample"},
        ],
        links=[
            {
                "link_id": "sample-link-ab",
                "from_node": "sample-node-a",
                "to_node": "sample-node-b",
                "status": "sample",
            }
        ],
    )
