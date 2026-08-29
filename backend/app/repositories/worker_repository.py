"""Transaction-safe persistence primitives for durable workers."""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.worker import Worker
from app.workforce.status import WorkerStatus


class WorkerRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(
        self,
        name: str,
        worker_type: str,
        capabilities: list[str] | None = None,
        status: WorkerStatus = WorkerStatus.OFFLINE,
    ) -> Worker:
        now = self._utc_now()
        worker = Worker(
            name=name,
            worker_type=worker_type,
            capabilities=list(capabilities or []),
            status=WorkerStatus(status).value,
            created_at=now,
            updated_at=now,
        )
        self.db.add(worker)
        self.db.commit()
        self.db.refresh(worker)
        return worker

    def get_by_name(self, name: str) -> Worker | None:
        return self.db.get(Worker, name)

    def ensure(self, worker) -> Worker:
        """Create a durable catalog row without resetting existing state."""
        existing = self.get_by_name(worker.name)
        if existing is not None:
            return existing
        try:
            return self.create(
                name=worker.name,
                worker_type=worker.worker_type,
                capabilities=worker.capabilities,
                status=worker.status,
            )
        except IntegrityError:
            self.db.rollback()
            existing = self.get_by_name(worker.name)
            if existing is None:
                raise
            return existing

    def list_by_status(self, status: WorkerStatus):
        return (
            self.db.query(Worker)
            .filter(Worker.status == WorkerStatus(status).value)
            .order_by(Worker.name.asc())
            .all()
        )

    def list_online(self):
        return self.list_by_status(WorkerStatus.ONLINE)

    def claim(self, worker_name: str, mission_id: str) -> bool:
        """Atomically claim an online, unassigned worker across processes."""
        now = self._utc_now()
        result = self.db.execute(
            update(Worker)
            .where(Worker.name == worker_name)
            .where(Worker.status == WorkerStatus.ONLINE.value)
            .where(Worker.current_mission_id.is_(None))
            .values(
                status=WorkerStatus.BUSY.value,
                current_mission_id=mission_id,
                updated_at=now,
                last_assigned_at=now,
            )
        )
        self.db.commit()
        return result.rowcount == 1

    def release(
        self,
        worker_name: str,
        mission_id: str,
        success: bool,
        commit: bool = True,
    ) -> bool:
        """Atomically release an owned worker and advance terminal metrics once."""
        now = self._utc_now()
        failed_increment = 0 if success else 1
        completed = Worker.missions_completed + 1
        failed = Worker.missions_failed + failed_increment
        result = self.db.execute(
            update(Worker)
            .where(Worker.name == worker_name)
            .where(Worker.status == WorkerStatus.BUSY.value)
            .where(Worker.current_mission_id == mission_id)
            .values(
                status=WorkerStatus.ONLINE.value,
                current_mission_id=None,
                missions_completed=completed,
                missions_failed=failed,
                success_rate=((completed - failed) * 100.0 / completed),
                updated_at=now,
                last_released_at=now,
            )
        )
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return result.rowcount == 1
