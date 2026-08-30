"""Caller-owned append-only M8A suppression persistence."""

from sqlalchemy.exc import IntegrityError

from app.crm.contracts import CRMError, PersistenceResult
from app.models.crm import SuppressionEvent


class SuppressionRepository:
    def __init__(self, db):
        self.db = db

    def by_source(self, source_namespace: str, source_event_key: str) -> SuppressionEvent | None:
        return self.db.query(SuppressionEvent).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key,
        ).one_or_none()

    def append(self, event: SuppressionEvent) -> PersistenceResult:
        existing = self.by_source(event.source_namespace, event.source_event_key)
        if existing is not None:
            return self._same_or_conflict(existing, event)
        try:
            with self.db.begin_nested():
                self.db.add(event)
                self.db.flush()
            return PersistenceResult(event, False)
        except IntegrityError as exc:
            existing = self.by_source(event.source_namespace, event.source_event_key)
            if existing is None:
                raise CRMError("SUPPRESSION_EVENT_CONFLICT", "suppression-event identity could not be persisted") from exc
            return self._same_or_conflict(existing, event)

    @staticmethod
    def _same_or_conflict(existing: SuppressionEvent, proposed: SuppressionEvent) -> PersistenceResult:
        if existing.event_fingerprint != proposed.event_fingerprint:
            raise CRMError("IDEMPOTENCY_CONFLICT", "suppression event identity conflicts with immutable content")
        return PersistenceResult(existing, True)
