"""Atomic caller-owned creation and execution revalidation for M9A."""

from app.models.crm import ContactPoint
from app.models.outreach import OutreachIntent, OutreachMessage
from app.outreach.contracts import (
    OUTREACH_ELIGIBILITY_POLICY_VERSION,
    ContactabilityEvidenceSnapshot,
    CreateOutreachIntentRequest,
    OutreachCreationResult,
    OutreachEligibilityFacts,
    OutreachError,
    aware_utc,
)
from app.outreach.eligibility import evaluate_outreach_eligibility
from app.repositories.outreach_intent_repository import OutreachIntentRepository
from app.repositories.outreach_message_repository import OutreachMessageRepository
from app.services.contactability_evaluation_service import ContactabilityEvaluationService


class OutreachIntentService:
    def __init__(self, db):
        self.db = db
        self.intents = OutreachIntentRepository(db)
        self.messages = OutreachMessageRepository(db)
        self.contactability = ContactabilityEvaluationService(db)

    def create_or_reuse(self, request: CreateOutreachIntentRequest) -> OutreachCreationResult:
        if not isinstance(request, CreateOutreachIntentRequest):
            raise OutreachError("INVALID_CONTRACT", "request must use the M9A contract")

        existing = self.intents.by_source(request.source_namespace, request.source_event_key)
        if existing is not None:
            result = self.intents.require_same(existing, request.request_fingerprint)
            message = self.messages.by_intent(existing.id)
            if message is None:
                raise OutreachError("INCOMPLETE_INTENT", "outreach intent has no immutable message")
            if message.content_fingerprint != request.message.content_fingerprint:
                raise OutreachError("IDEMPOTENCY_CONFLICT", "outreach message conflicts with immutable content")
            return OutreachCreationResult(existing, message, result.reused)

        contact_point = self.db.get(ContactPoint, request.contact_point_id)
        if contact_point is None:
            raise OutreachError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
        if contact_point.lead_id != request.lead_id:
            raise OutreachError("CONTACT_POINT_LEAD_MISMATCH", "contact point does not belong to Lead")

        m8_result = self.contactability.evaluate_point(
            request.lead_id, request.contact_point_id,
            channel=request.channel, purpose_key=request.purpose_key,
            evaluated_as_of=request.evaluated_as_of,
        )
        eligibility = evaluate_outreach_eligibility(OutreachEligibilityFacts(
            request.lead_id, request.contact_point_id, request.channel,
            request.purpose_key, m8_result, True,
        ))
        if not eligibility.eligible:
            raise OutreachError("INELIGIBLE", "outreach request is not eligible", eligibility.reason_codes)

        evidence = ContactabilityEvidenceSnapshot(
            lead_id=m8_result.lead_id,
            contact_point_id=m8_result.contact_point_id,
            channel=m8_result.channel,
            purpose_key=m8_result.purpose_key,
            state=m8_result.state,
            evaluated_as_of=m8_result.evaluated_as_of,
            winning_state_event_id=m8_result.winning_state_event_id,
            winning_permission_event_id=m8_result.winning_permission_event_id,
            winning_suppression_event_ids=m8_result.suppression.winning_event_ids,
            reason_codes=m8_result.reason_codes,
            policy_version=OUTREACH_ELIGIBILITY_POLICY_VERSION,
            decision_fingerprint=eligibility.decision_fingerprint,
        ).to_dict()
        intent_result = self.intents.create_or_reuse(OutreachIntent(
            lead_id=request.lead_id,
            contact_point_id=request.contact_point_id,
            channel=request.channel,
            purpose_key=request.purpose_key,
            source_namespace=request.source_namespace,
            source_event_key=request.source_event_key,
            request_fingerprint=request.request_fingerprint,
            eligibility_policy_version=OUTREACH_ELIGIBILITY_POLICY_VERSION,
            creation_contactability_state=m8_result.state,
            contactability_evaluated_as_of=m8_result.evaluated_as_of,
            contactability_decision_fingerprint=eligibility.decision_fingerprint,
            contactability_evidence=evidence,
        ))
        message_result = self.messages.create_or_reuse(OutreachMessage(
            outreach_intent_id=intent_result.record.id,
            subject=request.message.subject,
            body=request.message.body,
            content_format=request.message.content_format,
            channel_metadata=request.message.channel_metadata,
            content_fingerprint=request.message.content_fingerprint,
        ))
        return OutreachCreationResult(intent_result.record, message_result.record, intent_result.reused)

    def revalidate_for_execution(self, outreach_intent_id: str, evaluated_as_of):
        intent = self.intents.get(outreach_intent_id)
        if intent is None:
            raise OutreachError("INTENT_NOT_FOUND", "outreach intent does not exist")
        message = self.messages.by_intent(intent.id)
        if message is None:
            raise OutreachError("INCOMPLETE_INTENT", "outreach intent has no immutable message")
        evaluated_as_of = aware_utc(evaluated_as_of, "evaluated_as_of")
        result = self.contactability.evaluate_point(
            intent.lead_id, intent.contact_point_id,
            channel=intent.channel, purpose_key=intent.purpose_key,
            evaluated_as_of=evaluated_as_of,
        )
        return evaluate_outreach_eligibility(OutreachEligibilityFacts(
            intent.lead_id, intent.contact_point_id, intent.channel,
            intent.purpose_key, result, bool(message.body.strip()),
        ))
