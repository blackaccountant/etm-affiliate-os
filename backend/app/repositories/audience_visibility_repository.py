"""Read-only query repository for UIF5D audience operator visibility."""

from sqlalchemy.orm import Session

from app.models.audience import (
    AudienceProfile,
    AudienceQualificationAssessment,
    AudienceSegment,
    AudienceSegmentMembership,
    AudienceSegmentRevision,
    AudienceSignal,
)


class AudienceVisibilityRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_profiles(self, limit: int = 50):
        return (
            self.db.query(AudienceProfile)
            .order_by(AudienceProfile.derived_at.desc(), AudienceProfile.id.desc())
            .limit(limit)
            .all()
        )

    def list_signals(self, limit: int = 50):
        return (
            self.db.query(AudienceSignal)
            .order_by(AudienceSignal.derived_at.desc(), AudienceSignal.id.desc())
            .limit(limit)
            .all()
        )

    def list_qualifications(self, limit: int = 50):
        return (
            self.db.query(AudienceQualificationAssessment)
            .order_by(
                AudienceQualificationAssessment.derived_at.desc(),
                AudienceQualificationAssessment.id.desc(),
            )
            .limit(limit)
            .all()
        )

    def list_segments(self, limit: int = 50):
        return (
            self.db.query(AudienceSegment)
            .order_by(AudienceSegment.created_at.desc(), AudienceSegment.id.desc())
            .limit(limit)
            .all()
        )

    def list_segment_revisions(self, limit: int = 50):
        return (
            self.db.query(AudienceSegmentRevision)
            .order_by(
                AudienceSegmentRevision.created_at.desc(),
                AudienceSegmentRevision.id.desc(),
            )
            .limit(limit)
            .all()
        )

    def list_memberships(self, limit: int = 50):
        return (
            self.db.query(AudienceSegmentMembership)
            .order_by(
                AudienceSegmentMembership.evaluated_at.desc(),
                AudienceSegmentMembership.id.desc(),
            )
            .limit(limit)
            .all()
        )
