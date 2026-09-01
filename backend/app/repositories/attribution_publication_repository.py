"""Caller-owned persistence for strongly referenced attribution publications."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.attribution import AttributionPublication


class AttributionPublicationRepository:
    def __init__(self, db):
        self.db = db

    def get(self, publication_id: str):
        return self.db.get(AttributionPublication, publication_id)

    def by_legacy_queue(self, queue_id: int):
        return self.db.query(AttributionPublication).filter_by(legacy_publishing_queue_id=queue_id).one_or_none()

    def by_distribution_run(self, run_id: str):
        return self.db.query(AttributionPublication).filter_by(distribution_run_id=run_id).one_or_none()

    def create_or_reuse(self, record: AttributionPublication):
        lookup = (
            (lambda: self.by_legacy_queue(record.legacy_publishing_queue_id))
            if record.legacy_publishing_queue_id is not None
            else (lambda: self.by_distribution_run(record.distribution_run_id))
        )
        existing = lookup()
        if existing is not None:
            return existing
        if self.db.bind.dialect.name == "postgresql":
            values = {
                column.name: getattr(record, column.name)
                for column in AttributionPublication.__table__.columns
                if column.name != "id" or getattr(record, column.name) is not None
            }
            result = self.db.execute(
                pg_insert(AttributionPublication).values(**values).on_conflict_do_nothing().returning(AttributionPublication.id)
            ).scalar_one_or_none()
            return self.get(result) if result is not None else lookup()
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return record
        except IntegrityError:
            existing = lookup()
            if existing is None:
                raise
            return existing
