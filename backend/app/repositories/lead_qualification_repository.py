"""Caller-owned immutable persistence for M8C Lead qualification links."""

from sqlalchemy.exc import IntegrityError

from app.audience.qualification_contracts import QualificationStatus
from app.crm.contracts import CRMError, PersistenceResult
from app.models.audience import AudienceQualificationAssessment
from app.models.crm_relationships import LeadQualificationLink


class LeadQualificationRepository:
    QUALIFYING_STATUSES = (
        QualificationStatus.QUALIFIED.value,
        QualificationStatus.HIGH_INTENT.value,
    )

    def __init__(self, db):
        self.db = db

    def by_identity(self, lead_id: str, assessment_id: str) -> LeadQualificationLink | None:
        return self.db.query(LeadQualificationLink).filter_by(
            lead_id=lead_id, assessment_id=assessment_id
        ).one_or_none()

    def list_for_lead(self, lead_id: str):
        return self.db.query(LeadQualificationLink).filter_by(lead_id=lead_id).order_by(
            LeadQualificationLink.linked_at, LeadQualificationLink.id
        ).all()

    def has_qualifying_assessment(self, lead_id: str) -> bool:
        return self.db.query(LeadQualificationLink.id).join(
            AudienceQualificationAssessment,
            AudienceQualificationAssessment.id == LeadQualificationLink.assessment_id,
        ).filter(
            LeadQualificationLink.lead_id == lead_id,
            AudienceQualificationAssessment.qualification_status.in_(self.QUALIFYING_STATUSES),
        ).first() is not None

    def create_or_reuse(self, link: LeadQualificationLink) -> PersistenceResult:
        existing = self.by_identity(link.lead_id, link.assessment_id)
        if existing is not None:
            return PersistenceResult(existing, True)
        try:
            with self.db.begin_nested():
                self.db.add(link)
                self.db.flush()
            return PersistenceResult(link, False)
        except IntegrityError as exc:
            existing = self.by_identity(link.lead_id, link.assessment_id)
            if existing is None:
                raise CRMError(
                    "QUALIFICATION_LINK_CONFLICT",
                    "qualification link identity could not be persisted",
                ) from exc
            return PersistenceResult(existing, True)
