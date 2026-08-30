"""Caller-owned append-only M9B delivery-event persistence."""

from dataclasses import dataclass

from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.outreach.contracts import OutreachError


@dataclass(frozen=True)
class DeliveryEventPersistenceResult:
    record: OutreachDeliveryEvent
    reused: bool


class OutreachDeliveryEventRepository:
    def __init__(self, db):
        self.db = db

    def by_source(self, source_namespace: str, source_event_key: str) -> OutreachDeliveryEvent | None:
        return self.db.query(OutreachDeliveryEvent).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key,
        ).one_or_none()

    def by_attempt_sequence(self, delivery_attempt_id: str, sequence_number: int) -> OutreachDeliveryEvent | None:
        return self.db.query(OutreachDeliveryEvent).filter_by(
            delivery_attempt_id=delivery_attempt_id, sequence_number=sequence_number,
        ).one_or_none()

    def list_ordered(self, delivery_attempt_id: str):
        return self.db.query(OutreachDeliveryEvent).filter_by(
            delivery_attempt_id=delivery_attempt_id,
        ).order_by(OutreachDeliveryEvent.sequence_number).all()

    def lock_attempt(self, delivery_attempt_id: str) -> OutreachDeliveryAttempt | None:
        return self.db.query(OutreachDeliveryAttempt).filter(
            OutreachDeliveryAttempt.id == delivery_attempt_id,
        ).with_for_update().one_or_none()

    def append_or_reuse(self, event: OutreachDeliveryEvent) -> DeliveryEventPersistenceResult:
        existing = self.by_source(event.source_namespace, event.source_event_key)
        if existing is not None:
            return self.require_same(existing, event.event_fingerprint)
        existing_sequence = self.by_attempt_sequence(event.delivery_attempt_id, event.sequence_number)
        if existing_sequence is not None:
            return self._sequence_conflict(existing_sequence, event)
        self.db.add(event)
        self.db.flush()
        return DeliveryEventPersistenceResult(event, False)

    @staticmethod
    def require_same(existing: OutreachDeliveryEvent, event_fingerprint: str) -> DeliveryEventPersistenceResult:
        if existing.event_fingerprint != event_fingerprint:
            raise OutreachError("IDEMPOTENCY_CONFLICT", "delivery-event identity conflicts with immutable content")
        return DeliveryEventPersistenceResult(existing, True)

    @staticmethod
    def _sequence_conflict(existing: OutreachDeliveryEvent, proposed: OutreachDeliveryEvent) -> DeliveryEventPersistenceResult:
        if (
            existing.source_namespace != proposed.source_namespace
            or existing.source_event_key != proposed.source_event_key
        ):
            raise OutreachError("IDEMPOTENCY_CONFLICT", "delivery-event sequence has a different source identity")
        return OutreachDeliveryEventRepository.require_same(existing, proposed.event_fingerprint)
