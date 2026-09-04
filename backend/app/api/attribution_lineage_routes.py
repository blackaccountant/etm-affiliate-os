"""Read-only HTTP surface for durable attribution lineage visibility."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.attribution_lineage_schemas import AttributionLineageSnapshotResponse
from app.dependencies import get_db
from app.repositories.attribution_lineage_visibility_repository import (
    AttributionLineageVisibilityRepository,
)
from app.services.attribution_lineage_visibility_service import (
    AttributionLineageVisibilityService,
)


router = APIRouter(prefix="/attribution", tags=["Attribution"])


@router.get("/lineage", response_model=AttributionLineageSnapshotResponse)
def get_attribution_lineage(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return recent immutable attribution references without inferring or mutating lineage."""
    return AttributionLineageVisibilityService(
        AttributionLineageVisibilityRepository(db)
    ).snapshot(limit)
