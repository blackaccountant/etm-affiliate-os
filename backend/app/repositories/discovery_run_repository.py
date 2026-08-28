"""Transaction-safe persistence for discovery run identity and lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.discovery.contracts import DiscoveryRunCreate, DiscoveryRunStatus
from app.models.discovery import DiscoveryRun


class DiscoveryRunRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, payload: DiscoveryRunCreate) -> DiscoveryRun:
        """Create a run or return the durable idempotent predecessor."""
        now = self._utc_now()
        record = DiscoveryRun(
            id=str(uuid4()),
            input_type=payload.input_type.value,
            input_value=payload.input_value,
            input_data=payload.input_data,
            status=DiscoveryRunStatus.CREATED.value,
            idempotency_key=payload.idempotency_key,
            created_at=now,
            updated_at=now,
        )
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if payload.idempotency_key is None:
                raise
            existing = self.get_by_idempotency_key(payload.idempotency_key)
            if existing is None:
                raise
            return existing
        self.db.refresh(record)
        return record

    def get_by_id(self, run_id: str) -> DiscoveryRun | None:
        return self.db.get(DiscoveryRun, run_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> DiscoveryRun | None:
        return self.db.query(DiscoveryRun).filter(DiscoveryRun.idempotency_key == idempotency_key).first()

    def update_status(
        self,
        run_id: str,
        status: DiscoveryRunStatus,
        last_error: str | None = None,
    ) -> DiscoveryRun | None:
        record = self.get_by_id(run_id)
        if record is None:
            return None
        record.status = DiscoveryRunStatus(status).value
        record.last_error = last_error
        record.updated_at = self._utc_now()
        record.completed_at = record.updated_at if status in {DiscoveryRunStatus.COMPLETED, DiscoveryRunStatus.FAILED} else None
        self.db.commit()
        self.db.refresh(record)
        return record

    def update_counters(
        self,
        run_id: str,
        candidate_count: int | None = None,
        verified_count: int | None = None,
        selected_count: int | None = None,
    ) -> DiscoveryRun | None:
        record = self.get_by_id(run_id)
        if record is None:
            return None
        for field, value in {
            "candidate_count": candidate_count,
            "verified_count": verified_count,
            "selected_count": selected_count,
        }.items():
            if value is not None:
                if value < 0:
                    raise ValueError(f"{field} cannot be negative")
                setattr(record, field, value)
        record.updated_at = self._utc_now()
        self.db.commit()
        self.db.refresh(record)
        return record
