"""Read-only HTTP surface for durable audience intelligence visibility."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.audience_visibility_schemas import (
    AudienceProfileVisibilityResponse,
    AudienceQualificationVisibilityResponse,
    AudienceSegmentMembershipVisibilityResponse,
    AudienceSegmentRevisionVisibilityResponse,
    AudienceSegmentVisibilityResponse,
    AudienceSignalVisibilityResponse,
    AudienceVisibilitySnapshotResponse,
)
from app.dependencies import get_db
from app.repositories.audience_visibility_repository import AudienceVisibilityRepository
from app.services.audience_visibility_service import AudienceVisibilityService


router = APIRouter(prefix="/audience", tags=["Audience"])


@router.get("/visibility", response_model=AudienceVisibilitySnapshotResponse)
def get_audience_visibility(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return recent immutable audience intelligence without resolving identities or mutating state."""
    snapshot = AudienceVisibilityService(AudienceVisibilityRepository(db)).snapshot(limit)
    return AudienceVisibilitySnapshotResponse(
        profiles=[AudienceProfileVisibilityResponse.model_validate(item) for item in snapshot["profiles"]],
        signals=[AudienceSignalVisibilityResponse.model_validate(item) for item in snapshot["signals"]],
        qualifications=[AudienceQualificationVisibilityResponse.model_validate(item) for item in snapshot["qualifications"]],
        segments=[AudienceSegmentVisibilityResponse.model_validate(item) for item in snapshot["segments"]],
        segment_revisions=[AudienceSegmentRevisionVisibilityResponse.model_validate(item) for item in snapshot["segment_revisions"]],
        memberships=[AudienceSegmentMembershipVisibilityResponse.model_validate(item) for item in snapshot["memberships"]],
    )
