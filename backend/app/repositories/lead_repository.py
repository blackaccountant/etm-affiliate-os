"""Caller-owned persistence for M8A CRM Leads."""

from sqlalchemy.exc import IntegrityError

from app.crm.contracts import CRMError, PersistenceResult
from app.models.crm import Lead


class LeadRepository:
    def __init__(self, db):
        self.db = db

    def get(self, lead_id: str) -> Lead | None:
        return self.db.get(Lead, lead_id)

    def by_subject(self, subject_id: str) -> Lead | None:
        return self.db.query(Lead).filter_by(subject_id=subject_id).one_or_none()

    def create_or_reuse(self, lead: Lead) -> PersistenceResult:
        if lead.subject_id is not None:
            existing = self.by_subject(lead.subject_id)
            if existing is not None:
                return PersistenceResult(existing, True)
        try:
            with self.db.begin_nested():
                self.db.add(lead)
                self.db.flush()
            return PersistenceResult(lead, False)
        except IntegrityError as exc:
            existing = lead.subject_id and self.by_subject(lead.subject_id)
            if existing is None:
                raise CRMError("LEAD_CONFLICT", "lead identity could not be persisted") from exc
            return PersistenceResult(existing, True)
