"""Conflict-safe append-only attribution-fact persistence."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.attribution.contracts import AttributionIdempotencyConflict
from app.models.attribution import AttributionFact


class AttributionFactRepository:
    def __init__(self, db):
        self.db = db

    def get(self, fact_id: str):
        return self.db.get(AttributionFact, fact_id)

    def by_source(self, namespace: str, event_key_digest: str):
        return self.db.query(AttributionFact).filter_by(
            source_namespace=namespace, source_event_key_digest=event_key_digest,
        ).one_or_none()

    @staticmethod
    def _same(existing: AttributionFact, fingerprint: str):
        if existing.source_fingerprint != fingerprint:
            raise AttributionIdempotencyConflict("fact source identity conflicts with immutable content")
        return existing

    def append_or_reuse(self, record: AttributionFact):
        existing = self.by_source(record.source_namespace, record.source_event_key_digest)
        if existing is not None:
            return self._same(existing, record.source_fingerprint)
        if self.db.bind.dialect.name == "postgresql":
            values = {
                column.name: getattr(record, column.name)
                for column in AttributionFact.__table__.columns
                if column.name != "id" or getattr(record, column.name) is not None
            }
            result = self.db.execute(
                pg_insert(AttributionFact).values(**values)
                .on_conflict_do_nothing(constraint="uq_attribution_facts_source")
                .returning(AttributionFact.id)
            ).scalar_one_or_none()
            if result is not None:
                return self.get(result)
            return self._same(self.by_source(record.source_namespace, record.source_event_key_digest), record.source_fingerprint)
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return record
        except IntegrityError:
            existing = self.by_source(record.source_namespace, record.source_event_key_digest)
            if existing is None:
                raise
            return self._same(existing, record.source_fingerprint)
