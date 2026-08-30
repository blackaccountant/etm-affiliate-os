"""Caller-owned immutable one-to-one OutreachMessage persistence."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.models.outreach import OutreachMessage
from app.outreach.contracts import OutreachError


@dataclass(frozen=True)
class MessagePersistenceResult:
    record: OutreachMessage
    reused: bool


class OutreachMessageRepository:
    def __init__(self, db):
        self.db = db

    def by_intent(self, intent_id: str) -> OutreachMessage | None:
        return self.db.query(OutreachMessage).filter_by(outreach_intent_id=intent_id).one_or_none()

    def create_or_reuse(self, message: OutreachMessage) -> MessagePersistenceResult:
        existing = self.by_intent(message.outreach_intent_id)
        if existing is not None:
            return self._same_or_conflict(existing, message.content_fingerprint)
        try:
            with self.db.begin_nested():
                self.db.add(message)
                self.db.flush()
            return MessagePersistenceResult(message, False)
        except IntegrityError as exc:
            existing = self.by_intent(message.outreach_intent_id)
            if existing is None:
                raise OutreachError("MESSAGE_PERSISTENCE_CONFLICT", "outreach message could not be persisted") from exc
            return self._same_or_conflict(existing, message.content_fingerprint)

    @staticmethod
    def _same_or_conflict(existing: OutreachMessage, content_fingerprint: str) -> MessagePersistenceResult:
        if existing.content_fingerprint != content_fingerprint:
            raise OutreachError("IDEMPOTENCY_CONFLICT", "outreach message conflicts with immutable content")
        return MessagePersistenceResult(existing, True)
