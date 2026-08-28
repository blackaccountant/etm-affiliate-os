"""Transaction-safe persistence primitives for durable missions."""

import json
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.mission.status import MissionStatus
from app.models.mission_record import MissionRecord


_UNSET = object()
_TERMINAL_STATUSES = {MissionStatus.COMPLETED, MissionStatus.FAILED}


class MissionRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _serialize(value):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value)

    def create(
        self,
        mission_id: str,
        name: str,
        objective: str,
        workflow_name: str,
        status: MissionStatus = MissionStatus.CREATED,
        input_data=None,
        required_capability: str | None = None,
        idempotency_key: str | None = None,
        current_worker_name: str | None = None,
        result_data=None,
        last_error: str | None = None,
    ) -> MissionRecord:
        """Create a mission or return its idempotent predecessor.

        The unique database constraint is the final concurrency boundary.  A
        duplicate-key IntegrityError is rolled back and resolved by lookup.
        """
        now = self._utc_now()
        record = MissionRecord(
            id=mission_id,
            name=name,
            objective=objective,
            workflow_name=workflow_name,
            status=MissionStatus(status).value,
            input_data=self._serialize(input_data),
            required_capability=required_capability,
            idempotency_key=idempotency_key,
            current_worker_name=current_worker_name,
            result_data=self._serialize(result_data),
            last_error=last_error,
            created_at=now,
            updated_at=now,
        )
        self.db.add(record)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if idempotency_key is None:
                raise
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return existing

        self.db.refresh(record)
        return record

    def get_by_id(self, mission_id: str) -> MissionRecord | None:
        return self.db.get(MissionRecord, mission_id)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MissionRecord | None:
        return (
            self.db.query(MissionRecord)
            .filter(MissionRecord.idempotency_key == idempotency_key)
            .first()
        )

    def list_by_status(self, status: MissionStatus):
        return (
            self.db.query(MissionRecord)
            .filter(MissionRecord.status == MissionStatus(status).value)
            .order_by(MissionRecord.created_at.asc())
            .all()
        )

    def update_status(
        self,
        mission_id: str,
        status: MissionStatus,
        result_data=_UNSET,
        last_error=_UNSET,
        current_worker_name=_UNSET,
    ) -> MissionRecord | None:
        record = self.get_by_id(mission_id)
        if record is None:
            return None

        target_status = MissionStatus(status)
        record.status = target_status.value
        record.updated_at = self._utc_now()
        record.completed_at = (
            record.updated_at if target_status in _TERMINAL_STATUSES else None
        )

        if result_data is not _UNSET:
            record.result_data = self._serialize(result_data)
        if last_error is not _UNSET:
            record.last_error = last_error
        if current_worker_name is not _UNSET:
            record.current_worker_name = current_worker_name

        self.db.commit()
        self.db.refresh(record)
        return record
