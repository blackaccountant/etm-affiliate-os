"""Persistence primitives for idempotent DistributionRun creation."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.distribution_run import DistributionRun


class DistributionRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, run_id: str) -> DistributionRun | None:
        return self.db.get(DistributionRun, run_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> DistributionRun | None:
        return self.db.query(DistributionRun).filter_by(idempotency_key=idempotency_key).first()

    def list_by_artifact(self, artifact_id: str) -> list[DistributionRun]:
        return self.db.query(DistributionRun).filter_by(generated_content_artifact_id=artifact_id).order_by(DistributionRun.created_at.asc()).all()

    def create(self, **values) -> DistributionRun:
        """Create exactly one durable run, resolving a unique-key race by reread."""
        row = DistributionRun(**values)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.get_by_idempotency_key(values["idempotency_key"])
            if existing is None:
                raise
            return existing
        self.db.refresh(row)
        return row
