"""Locked, deterministic allocation for append-only cold delivery events."""

from sqlalchemy.exc import IntegrityError

from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperationState
from app.outreach.contracts import OutreachError
from app.outreach.cold_delivery_contracts import pii_bounded_payload


class ColdDeliveryEventRepository:
    def __init__(self, db): self.db = db
    def by_source(self, namespace, key): return self.db.query(ColdDeliveryEvent).filter_by(source_namespace=namespace, source_event_key=key).one_or_none()
    def lock_state(self, operation_id): return self.db.query(ColdDeliveryOperationState).filter_by(operation_id=operation_id).with_for_update().one_or_none()
    def append_or_reuse(self, *, operation_id, event_type, occurred_at, source_namespace, source_event_key, event_fingerprint, safe_payload):
        safe_payload = pii_bounded_payload(safe_payload)
        existing = self.by_source(source_namespace, source_event_key)
        if existing is not None: return self._same(existing, event_fingerprint)
        state = self.lock_state(operation_id)
        if state is None: raise OutreachError("OPERATION_STATE_NOT_FOUND", "cold operation has no control state")
        existing = self.by_source(source_namespace, source_event_key)
        if existing is not None: return self._same(existing, event_fingerprint)
        event = ColdDeliveryEvent(operation_id=operation_id, sequence_number=state.next_event_sequence, event_type=event_type, occurred_at=occurred_at, source_namespace=source_namespace, source_event_key=source_event_key, event_fingerprint=event_fingerprint, safe_payload=safe_payload)
        try:
            with self.db.begin_nested(): self.db.add(event); state.next_event_sequence += 1; self.db.flush()
        except IntegrityError:
            existing = self.by_source(source_namespace, source_event_key)
            if existing is None: raise
            return self._same(existing, event_fingerprint)
        return event, False
    @staticmethod
    def _same(existing, fingerprint):
        if existing.event_fingerprint != fingerprint: raise OutreachError("IDEMPOTENCY_CONFLICT", "cold delivery event conflicts with immutable content")
        return existing, True
