"""Caller-owned exact-idempotency persistence for OutreachIntent."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.models.outreach import OutreachIntent
from app.outreach.contracts import OutreachError


@dataclass(frozen=True)
class IntentPersistenceResult:
    record: OutreachIntent
    reused: bool


class OutreachIntentRepository:
    def __init__(self, db):
        self.db = db

    def get(self, intent_id: str) -> OutreachIntent | None:
        return self.db.get(OutreachIntent, intent_id)

    def by_source(self, source_namespace: str, source_event_key: str) -> OutreachIntent | None:
        return self.db.query(OutreachIntent).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key,
        ).one_or_none()

    def create_or_reuse(self, intent: OutreachIntent) -> IntentPersistenceResult:
        existing = self.by_source(intent.source_namespace, intent.source_event_key)
        if existing is not None:
            return self.require_same(existing, intent.request_fingerprint)
        try:
            with self.db.begin_nested():
                self.db.add(intent)
                self.db.flush()
            return IntentPersistenceResult(intent, False)
        except IntegrityError as exc:
            existing = self.by_source(intent.source_namespace, intent.source_event_key)
            if existing is None:
                raise OutreachError("INTENT_PERSISTENCE_CONFLICT", "outreach intent could not be persisted") from exc
            return self.require_same(existing, intent.request_fingerprint)

    @staticmethod
    def require_same(existing: OutreachIntent, request_fingerprint: str) -> IntentPersistenceResult:
        if existing.request_fingerprint != request_fingerprint:
            raise OutreachError("IDEMPOTENCY_CONFLICT", "outreach intent identity conflicts with immutable content")
        return IntentPersistenceResult(existing, True)
