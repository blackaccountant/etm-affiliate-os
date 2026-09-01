"""Caller-owned persistence for immutable attribution contexts."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.attribution import AttributionContext


class AttributionContextRepository:
    def __init__(self, db):
        self.db = db

    def get(self, context_id: str):
        return self.db.get(AttributionContext, context_id)

    def by_fingerprint(self, fingerprint: str):
        return self.db.query(AttributionContext).filter_by(context_fingerprint=fingerprint).one_or_none()

    def create_or_reuse(self, record: AttributionContext):
        existing = self.by_fingerprint(record.context_fingerprint)
        if existing is not None:
            return existing
        if self.db.bind.dialect.name == "postgresql":
            values = {
                column.name: getattr(record, column.name)
                for column in AttributionContext.__table__.columns
                if column.name != "id" or getattr(record, column.name) is not None
            }
            result = self.db.execute(
                pg_insert(AttributionContext).values(**values)
                .on_conflict_do_nothing(constraint="uq_attribution_contexts_fingerprint")
                .returning(AttributionContext.id)
            ).scalar_one_or_none()
            return self.get(result) if result is not None else self.by_fingerprint(record.context_fingerprint)
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return record
        except IntegrityError:
            existing = self.by_fingerprint(record.context_fingerprint)
            if existing is None:
                raise
            return existing
