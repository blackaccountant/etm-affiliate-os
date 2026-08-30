"""The single fenced, durable finalization authority for active attempts."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import uuid4

from sqlalchemy import update

from app.core.config import settings
from app.mission.status import MissionStatus
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.execution_lease import ExecutionLeaseAuthority
from app.workforce.status import WorkerStatus


@dataclass(frozen=True)
class OwnedLifecycleResult:
    status: str
    mission_status: MissionStatus
    successor: object | None = None


@dataclass(frozen=True)
class SuccessorOperationSpec:
    """Trusted, runtime-only description of a new durable operation."""

    name: str
    objective: str
    workflow: str
    required_capability: str | None
    idempotency_key: str
    payload: dict


@dataclass(frozen=True)
class SuccessorOperation:
    spec: SuccessorOperationSpec
    mission_id: str
    mission_name: str
    worker_name: str
    execution_id: int
    authority: ExecutionLeaseAuthority


class OwnedExecutionLifecycleCoordinator:
    """Atomically finalize an attempt still owned by its lease authority.

    This component deliberately contains no workflow or provider logic.  It is
    the one place an active execution may transition durable Execution, Mission,
    and Worker state after workflow invocation.
    """

    def __init__(self, db, workforce=None):
        self.db = db
        self.workforce = workforce
        self.executions = ExecutionRepository(db)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _serialize(value):
        return value if isinstance(value, str) else json.dumps(value, default=str)

    def _mission_update(self, mission_id, worker_name, status, *, result_data, last_error):
        now = self._now()
        result = self.db.execute(
            update(MissionRecord)
            .where(MissionRecord.id == mission_id)
            .where(MissionRecord.status == MissionStatus.RUNNING.value)
            .where(MissionRecord.current_worker_name == worker_name)
            .values(
                status=status.value,
                result_data=self._serialize(result_data),
                last_error=last_error,
                current_worker_name=None if status in {MissionStatus.COMPLETED, MissionStatus.FAILED} else worker_name,
                updated_at=now,
                completed_at=now if status in {MissionStatus.COMPLETED, MissionStatus.FAILED} else None,
            )
        )
        if result.rowcount != 1:
            raise ExecutionLeaseLostError("mission is no longer owned by the active execution")

    def _release_worker(self, worker_name, mission_id, *, success):
        try:
            released = WorkerRepository(self.db).release(
                worker_name, mission_id, success=success, commit=False,
            )
        except TypeError as exc:
            raise RuntimeError("Durable worker release failed inside owned lifecycle") from exc
        if not released:
            raise ExecutionLeaseLostError("worker is no longer owned by the active execution")

    def _verify_retry_worker(self, worker_name, mission_id):
        worker = self.db.get(Worker, worker_name)
        if (worker is None or worker.status != WorkerStatus.BUSY.value
                or worker.current_mission_id != mission_id):
            raise ExecutionLeaseLostError("worker is no longer owned by the active execution")

    def _commit_and_sync(self, worker_name, mission_name):
        self.db.commit()
        if self.workforce is not None:
            durable_worker = self.db.get(Worker, worker_name)
            if durable_worker is not None:
                self.workforce.sync_from_durable(durable_worker, mission_name)

    def _activate_successor(self, spec: SuccessorOperationSpec, preferred_worker_name: str):
        """Create a separately owned active operation without reopening its predecessor."""
        missions = MissionRepository(self.db)
        workers = WorkerRepository(self.db)
        successor = missions.create(
            mission_id=str(uuid4()), name=spec.name, objective=spec.objective,
            workflow_name=spec.workflow, input_data=spec.payload,
            required_capability=spec.required_capability, idempotency_key=spec.idempotency_key,
            commit=False,
        )
        if successor.status != MissionStatus.CREATED.value:
            raise RuntimeError("successor operation already exists")
        if not workers.claim(preferred_worker_name, successor.id, commit=False):
            raise RuntimeError("successor worker could not be claimed")
        successor.status = MissionStatus.RUNNING.value
        successor.current_worker_name = preferred_worker_name
        successor.updated_at = self._now()
        execution = self.executions.create(
            spec.workflow, "RUNNING", successor.id, successor.name, preferred_worker_name,
            input_data=json.dumps(spec.payload), commit=False,
        )
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        if not self.executions.acquire_lease(authority, settings.EXECUTION_LEASE_SECONDS, commit=False):
            raise RuntimeError("successor execution lease could not be acquired")
        return SuccessorOperation(spec, successor.id, successor.name, preferred_worker_name, execution.id, authority)

    def complete(self, authority, *, mission_id, mission_name, worker_name,
                 duration, result_data, result_payload, participant=None):
        try:
            spec = participant.apply(self.db, authority, "COMPLETED", result_payload) if participant is not None else None
            self.executions.complete_owned(
                authority, duration=duration, result_data=result_data, commit=False,
            )
            self._mission_update(
                mission_id, worker_name, MissionStatus.COMPLETED,
                result_data=result_payload, last_error=None,
            )
            self._release_worker(worker_name, mission_id, success=True)
            successor = self._activate_successor(spec, worker_name) if spec is not None else None
            self._commit_and_sync(worker_name, mission_name)
        except Exception:
            self.db.rollback()
            raise
        return OwnedLifecycleResult("COMPLETED", MissionStatus.COMPLETED, successor)

    def fail(self, authority, *, mission_id, mission_name, worker_name,
             duration, result_data, result_payload, error, failure_type, retry_count,
             participant=None):
        try:
            if participant is not None:
                participant.apply(self.db, authority, "FAILED", result_payload)
            self.executions.fail_owned(
                authority, error=error, failure_type=failure_type, duration=duration,
                retry_count=retry_count, commit=False,
            )
            self._mission_update(
                mission_id, worker_name, MissionStatus.FAILED,
                result_data=result_payload, last_error=error,
            )
            self._release_worker(worker_name, mission_id, success=False)
            self._commit_and_sync(worker_name, mission_name)
        except Exception:
            self.db.rollback()
            raise
        return OwnedLifecycleResult("FAILED", MissionStatus.FAILED)

    def schedule_retry(self, authority, *, mission_id, mission_name, worker_name,
                       result_data, result_payload, retry_count, max_retries,
                       next_retry_at, error, failure_type, participant=None):
        try:
            if participant is not None:
                participant.apply(self.db, authority, "RETRY_WAIT", result_payload)
            self.executions.schedule_retry_owned(
                authority, retry_count=retry_count, max_retries=max_retries,
                next_retry_at=next_retry_at, failure_type=failure_type,
                error=error, result_data=result_data, commit=False,
            )
            self._verify_retry_worker(worker_name, mission_id)
            self._mission_update(
                mission_id, worker_name, MissionStatus.RETRY_WAIT,
                result_data=result_payload, last_error=error,
            )
            self._commit_and_sync(worker_name, mission_name)
        except Exception:
            self.db.rollback()
            raise
        return OwnedLifecycleResult("QUEUED", MissionStatus.RETRY_WAIT)
