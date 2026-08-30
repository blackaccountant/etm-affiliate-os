"""Caller-owned persistence for M8A contact points and their immutable history."""

from sqlalchemy.exc import IntegrityError

from app.crm.contracts import CRMError, PersistenceResult
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent


class ContactPointRepository:
    def __init__(self, db):
        self.db = db

    def get(self, contact_point_id: str) -> ContactPoint | None:
        return self.db.get(ContactPoint, contact_point_id)

    def by_identity(self, kind: str, normalized_value: str) -> ContactPoint | None:
        return self.db.query(ContactPoint).filter_by(kind=kind, normalized_value=normalized_value).one_or_none()

    def create_or_reuse(self, contact_point: ContactPoint) -> PersistenceResult:
        existing = self.by_identity(contact_point.kind, contact_point.normalized_value)
        if existing is not None:
            return self._same_owner_or_conflict(existing, contact_point.lead_id)
        try:
            with self.db.begin_nested():
                self.db.add(contact_point)
                self.db.flush()
            return PersistenceResult(contact_point, False)
        except IntegrityError as exc:
            existing = self.by_identity(contact_point.kind, contact_point.normalized_value)
            if existing is None:
                raise CRMError("CONTACT_POINT_CONFLICT", "contact-point identity could not be persisted") from exc
            return self._same_owner_or_conflict(existing, contact_point.lead_id)

    @staticmethod
    def _same_owner_or_conflict(existing: ContactPoint, lead_id: str) -> PersistenceResult:
        if existing.lead_id != lead_id:
            raise CRMError("CONTACT_POINT_OWNERSHIP_CONFLICT", "contact point belongs to another Lead")
        return PersistenceResult(existing, True)

    def provenance_by_source(self, contact_point_id: str, source_namespace: str, source_event_id: str):
        return self.db.query(ContactPointProvenance).filter_by(
            contact_point_id=contact_point_id,
            source_namespace=source_namespace,
            source_event_id=source_event_id,
        ).one_or_none()

    def append_provenance(self, record: ContactPointProvenance) -> PersistenceResult:
        existing = self.provenance_by_source(record.contact_point_id, record.source_namespace, record.source_event_id)
        if existing is not None:
            return self._same_event_or_conflict(existing, record)
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return PersistenceResult(record, False)
        except IntegrityError as exc:
            existing = self.provenance_by_source(record.contact_point_id, record.source_namespace, record.source_event_id)
            if existing is None:
                raise CRMError("PROVENANCE_CONFLICT", "provenance identity could not be persisted") from exc
            return self._same_event_or_conflict(existing, record)

    def state_event_by_source(self, source_namespace: str, source_event_key: str):
        return self.db.query(ContactPointStateEvent).filter_by(
            source_namespace=source_namespace, source_event_key=source_event_key,
        ).one_or_none()

    def append_state_event(self, record: ContactPointStateEvent) -> PersistenceResult:
        existing = self.state_event_by_source(record.source_namespace, record.source_event_key)
        if existing is not None:
            return self._same_event_or_conflict(existing, record)
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return PersistenceResult(record, False)
        except IntegrityError as exc:
            existing = self.state_event_by_source(record.source_namespace, record.source_event_key)
            if existing is None:
                raise CRMError("STATE_EVENT_CONFLICT", "state-event identity could not be persisted") from exc
            return self._same_event_or_conflict(existing, record)

    @staticmethod
    def _same_event_or_conflict(existing, proposed) -> PersistenceResult:
        existing_fingerprint = getattr(existing, "event_fingerprint", None) or existing.provenance_fingerprint
        proposed_fingerprint = getattr(proposed, "event_fingerprint", None) or proposed.provenance_fingerprint
        if existing_fingerprint != proposed_fingerprint:
            raise CRMError("IDEMPOTENCY_CONFLICT", "event identity conflicts with immutable content")
        return PersistenceResult(existing, True)
