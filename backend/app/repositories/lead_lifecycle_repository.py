"""Caller-owned append-only persistence for M8C Lead lifecycle events."""

from sqlalchemy.exc import IntegrityError

from app.crm.contracts import CRMError, PersistenceResult
from app.models.crm import Lead
from app.models.crm_relationships import LeadLifecycleEvent


class LeadLifecycleRepository:
    def __init__(self, db):
        self.db = db

    def lock_lead(self, lead_id: str) -> Lead | None:
        return self.db.query(Lead).filter(Lead.id == lead_id).with_for_update().one_or_none()

    def list_ordered(self, lead_id: str):
        return self.db.query(LeadLifecycleEvent).filter_by(lead_id=lead_id).order_by(
            LeadLifecycleEvent.sequence_number
        ).all()

    def by_source(self, source_namespace: str, source_event_key: str) -> LeadLifecycleEvent | None:
        return self.db.query(LeadLifecycleEvent).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key
        ).one_or_none()

    def append_or_reuse(self, event: LeadLifecycleEvent) -> PersistenceResult:
        existing = self.by_source(event.source_namespace, event.source_event_key)
        if existing is not None:
            return self.same_event_or_conflict(existing, event.event_fingerprint)
        try:
            with self.db.begin_nested():
                self.db.add(event)
                self.db.flush()
            return PersistenceResult(event, False)
        except IntegrityError as exc:
            existing = self.by_source(event.source_namespace, event.source_event_key)
            if existing is None:
                raise CRMError(
                    "LIFECYCLE_EVENT_CONFLICT",
                    "lifecycle event identity could not be persisted",
                ) from exc
            return self.same_event_or_conflict(existing, event.event_fingerprint)

    @staticmethod
    def same_event_or_conflict(existing: LeadLifecycleEvent, fingerprint: str) -> PersistenceResult:
        if existing.event_fingerprint != fingerprint:
            raise CRMError("IDEMPOTENCY_CONFLICT", "event identity conflicts with immutable content")
        return PersistenceResult(existing, True)
