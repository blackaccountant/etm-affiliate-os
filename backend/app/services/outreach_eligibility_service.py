"""M9A orchestration over the frozen M8 point-contactability service."""

from app.outreach.contracts import OutreachEligibilityFacts, aware_utc
from app.outreach.eligibility import evaluate_outreach_eligibility
from app.services.contactability_evaluation_service import ContactabilityEvaluationService


class OutreachEligibilityService:
    def __init__(self, db):
        self.db = db
        self.contactability = ContactabilityEvaluationService(db)

    def evaluate(self, *, lead_id, contact_point_id, channel, purpose_key, evaluated_as_of, message_contract_valid=True):
        evaluated_as_of = aware_utc(evaluated_as_of, "evaluated_as_of")
        result = self.contactability.evaluate_point(
            lead_id, contact_point_id, channel=channel, purpose_key=purpose_key,
            evaluated_as_of=evaluated_as_of,
        )
        return evaluate_outreach_eligibility(OutreachEligibilityFacts(
            lead_id, contact_point_id, channel, purpose_key, result, message_contract_valid,
        )), result
