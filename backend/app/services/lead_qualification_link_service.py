"""M8C exact-subject bridge from frozen M7 assessments to CRM Leads."""

from app.crm.contracts import CRMError, required_text
from app.crm.lifecycle_contracts import LeadQualificationLinkResult
from app.models.audience import AudienceProfile, AudienceQualificationAssessment
from app.models.crm_relationships import LeadQualificationLink
from app.repositories.lead_qualification_repository import LeadQualificationRepository
from app.repositories.lead_repository import LeadRepository


class LeadQualificationLinkService:
    def __init__(self, db):
        self.db = db
        self.leads = LeadRepository(db)
        self.links = LeadQualificationRepository(db)

    def link(self, lead_id: str, assessment_id: str) -> LeadQualificationLinkResult:
        lead = self.leads.get(required_text(lead_id, "lead_id", 36))
        if lead is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")
        if lead.subject_id is None:
            raise CRMError("LEAD_SUBJECT_REQUIRED", "subjectless Lead cannot own qualification history")
        assessment = self.db.get(
            AudienceQualificationAssessment,
            required_text(assessment_id, "assessment_id", 36),
        )
        if assessment is None:
            raise CRMError("QUALIFICATION_ASSESSMENT_NOT_FOUND", "qualification assessment does not exist")
        profile = self.db.get(AudienceProfile, assessment.profile_id)
        if profile is None:
            raise CRMError("QUALIFICATION_PROFILE_NOT_FOUND", "qualification profile does not exist")
        if lead.subject_id != profile.subject_id:
            raise CRMError(
                "QUALIFICATION_SUBJECT_MISMATCH",
                "qualification assessment subject does not match Lead subject",
            )
        result = self.links.create_or_reuse(
            LeadQualificationLink(lead_id=lead.id, assessment_id=assessment.id)
        )
        return LeadQualificationLinkResult(result.record.id, result.reused)
