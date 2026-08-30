"""Caller-owned immutable persistence for M9B delivery attempts."""

from dataclasses import dataclass

from app.models.outreach import OutreachIntent
from app.models.outreach_delivery import OutreachDeliveryAttempt
from app.outreach.contracts import OutreachError


@dataclass(frozen=True)
class DeliveryAttemptPersistenceResult:
    record: OutreachDeliveryAttempt
    reused: bool


class OutreachDeliveryAttemptRepository:
    def __init__(self, db):
        self.db = db

    def get(self, attempt_id: str) -> OutreachDeliveryAttempt | None:
        return self.db.get(OutreachDeliveryAttempt, attempt_id)

    def by_source(self, source_namespace: str, source_event_key: str) -> OutreachDeliveryAttempt | None:
        return self.db.query(OutreachDeliveryAttempt).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key,
        ).one_or_none()

    def by_intent_number(self, outreach_intent_id: str, attempt_number: int) -> OutreachDeliveryAttempt | None:
        return self.db.query(OutreachDeliveryAttempt).filter_by(
            outreach_intent_id=outreach_intent_id, attempt_number=attempt_number,
        ).one_or_none()

    def lock_intent(self, outreach_intent_id: str) -> OutreachIntent | None:
        return self.db.query(OutreachIntent).filter(
            OutreachIntent.id == outreach_intent_id,
        ).with_for_update().one_or_none()

    def create_initial_or_reuse(self, attempt: OutreachDeliveryAttempt) -> DeliveryAttemptPersistenceResult:
        if attempt.attempt_number != 1:
            raise OutreachError(
                "INVALID_INITIAL_ATTEMPT_NUMBER",
                "M9B initial preparation requires attempt_number=1",
            )
        existing = self.by_source(attempt.source_namespace, attempt.source_event_key)
        if existing is not None:
            return self.require_same(existing, attempt.request_fingerprint)
        existing_number = self.by_intent_number(attempt.outreach_intent_id, attempt.attempt_number)
        if existing_number is not None:
            return self._number_conflict(existing_number, attempt)
        self.db.add(attempt)
        self.db.flush()
        return DeliveryAttemptPersistenceResult(attempt, False)

    @staticmethod
    def require_same(existing: OutreachDeliveryAttempt, request_fingerprint: str) -> DeliveryAttemptPersistenceResult:
        if existing.request_fingerprint != request_fingerprint:
            raise OutreachError("IDEMPOTENCY_CONFLICT", "delivery-attempt identity conflicts with immutable content")
        return DeliveryAttemptPersistenceResult(existing, True)

    @staticmethod
    def _number_conflict(existing: OutreachDeliveryAttempt, proposed: OutreachDeliveryAttempt) -> DeliveryAttemptPersistenceResult:
        if (
            existing.source_namespace == proposed.source_namespace
            and existing.source_event_key == proposed.source_event_key
        ):
            return OutreachDeliveryAttemptRepository.require_same(existing, proposed.request_fingerprint)
        raise OutreachError("INITIAL_ATTEMPT_ALREADY_EXISTS", "initial delivery attempt already exists")
