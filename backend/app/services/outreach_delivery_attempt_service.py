"""Atomic provider-neutral preparation of the M9B initial delivery attempt."""

from app.models.outreach import OutreachIntent
from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.outreach.contracts import OutreachError, PreparedOutreachMessage
from app.outreach.delivery_contracts import (
    DeliveryEventType,
    DeliveryPreparationResult,
    PreparedDeliveryEvidence,
    PrepareDeliveryAttemptRequest,
    prepared_event_fingerprint,
    prepared_event_source_identity,
)
from app.repositories.outreach_delivery_attempt_repository import OutreachDeliveryAttemptRepository
from app.repositories.outreach_delivery_event_repository import OutreachDeliveryEventRepository
from app.repositories.outreach_message_repository import OutreachMessageRepository
from app.services.outreach_eligibility_service import OutreachEligibilityService


class OutreachDeliveryAttemptService:
    """PREPARED is historical evidence; M9C must revalidate before any send."""

    def __init__(self, db):
        self.db = db
        self.attempts = OutreachDeliveryAttemptRepository(db)
        self.events = OutreachDeliveryEventRepository(db)
        self.messages = OutreachMessageRepository(db)
        self.eligibility = OutreachEligibilityService(db)

    def prepare_initial(self, request: PrepareDeliveryAttemptRequest) -> DeliveryPreparationResult:
        if not isinstance(request, PrepareDeliveryAttemptRequest):
            raise OutreachError("INVALID_CONTRACT", "request must use the M9B preparation contract")

        existing = self.attempts.by_source(request.source_namespace, request.source_event_key)
        if existing is not None:
            return self._reuse(existing, request.request_fingerprint)

        intent = self.db.get(OutreachIntent, request.outreach_intent_id)
        if intent is None:
            raise OutreachError("INTENT_NOT_FOUND", "outreach intent does not exist")
        message = self.messages.by_intent(intent.id)
        if message is None:
            raise OutreachError("INCOMPLETE_INTENT", "outreach intent has no immutable message")
        prepared = PreparedOutreachMessage(
            body=message.body, subject=message.subject,
            content_format=message.content_format, channel_metadata=message.channel_metadata,
        )
        if prepared.content_fingerprint != message.content_fingerprint:
            raise OutreachError("MESSAGE_INTEGRITY_CONFLICT", "outreach message fingerprint does not match content")

        eligibility, m8_result = self.eligibility.evaluate(
            lead_id=intent.lead_id,
            contact_point_id=intent.contact_point_id,
            channel=intent.channel,
            purpose_key=intent.purpose_key,
            evaluated_as_of=request.evaluated_as_of,
            message_contract_valid=True,
        )
        if not eligibility.eligible:
            raise OutreachError(eligibility.state, "delivery attempt is not eligible for preparation", eligibility.reason_codes)

        locked_intent = self.attempts.lock_intent(intent.id)
        if locked_intent is None:
            raise OutreachError("INTENT_NOT_FOUND", "outreach intent does not exist")
        existing = self.attempts.by_source(request.source_namespace, request.source_event_key)
        if existing is not None:
            return self._reuse(existing, request.request_fingerprint)
        existing_initial = self.attempts.by_intent_number(intent.id, 1)
        if existing_initial is not None:
            raise OutreachError("INITIAL_ATTEMPT_ALREADY_EXISTS", "initial delivery attempt already exists")

        evidence = PreparedDeliveryEvidence(
            outreach_intent_id=intent.id,
            lead_id=intent.lead_id,
            contact_point_id=intent.contact_point_id,
            channel=intent.channel,
            purpose_key=intent.purpose_key,
            eligibility=eligibility.state,
            contactability_state=eligibility.contactability_state,
            evaluated_as_of=eligibility.evaluated_as_of,
            policy_version=eligibility.policy_version,
            decision_fingerprint=eligibility.decision_fingerprint,
            winning_state_event_id=m8_result.winning_state_event_id,
            winning_permission_event_id=m8_result.winning_permission_event_id,
            winning_suppression_event_ids=m8_result.suppression.winning_event_ids,
            reason_codes=m8_result.reason_codes,
        ).to_dict()

        attempt_result = self.attempts.create_initial_or_reuse(OutreachDeliveryAttempt(
            outreach_intent_id=intent.id,
            attempt_number=1,
            source_namespace=request.source_namespace,
            source_event_key=request.source_event_key,
            request_fingerprint=request.request_fingerprint,
        ))
        if attempt_result.reused:
            return self._reuse(attempt_result.record, request.request_fingerprint)
        event_namespace, event_key = prepared_event_source_identity(attempt_result.record.id)
        event_result = self.events.append_or_reuse(OutreachDeliveryEvent(
            delivery_attempt_id=attempt_result.record.id,
            sequence_number=1,
            event_type=DeliveryEventType.PREPARED.value,
            occurred_at=request.evaluated_as_of,
            source_namespace=event_namespace,
            source_event_key=event_key,
            event_fingerprint=prepared_event_fingerprint(
                delivery_attempt_id=attempt_result.record.id,
                occurred_at=request.evaluated_as_of,
                safe_payload=evidence,
            ),
            safe_payload=evidence,
        ))
        return DeliveryPreparationResult(attempt_result.record, event_result.record, False)

    def _reuse(self, attempt, request_fingerprint: str) -> DeliveryPreparationResult:
        result = self.attempts.require_same(attempt, request_fingerprint)
        event = self.events.by_attempt_sequence(attempt.id, 1)
        if event is None or event.event_type != DeliveryEventType.PREPARED.value:
            raise OutreachError("INCOMPLETE_ATTEMPT", "delivery attempt has no PREPARED event")
        expected_namespace, expected_key = prepared_event_source_identity(attempt.id)
        if (event.source_namespace, event.source_event_key) != (expected_namespace, expected_key):
            raise OutreachError("EVENT_IDENTITY_CONFLICT", "PREPARED event identity is invalid")
        return DeliveryPreparationResult(result.record, event, True)
