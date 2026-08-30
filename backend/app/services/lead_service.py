"""M8A Lead persistence with AudienceSubject as authoritative identity."""

from app.crm.contracts import CRMError, required_text
from app.models.audience import AudienceSubject
from app.models.crm import Lead
from app.repositories.lead_repository import LeadRepository


class LeadService:
    def __init__(self, db):
        self.db = db
        self.leads = LeadRepository(db)

    def create_or_reuse(self, subject_id: str | None):
        if subject_id is None:
            return self.leads.create_or_reuse(Lead(subject_id=None))
        subject_id = required_text(subject_id, "subject_id", 36)
        if self.db.get(AudienceSubject, subject_id) is None:
            raise CRMError("SUBJECT_NOT_FOUND", "AudienceSubject does not exist")
        return self.leads.create_or_reuse(Lead(subject_id=subject_id))
