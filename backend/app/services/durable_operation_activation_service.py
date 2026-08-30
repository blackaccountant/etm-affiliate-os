"""Generic transaction-scoped activation of a durable operation."""

import json
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from app.core.config import settings
from app.mission.status import MissionStatus
from app.models.execution import Execution
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.execution_lease import ExecutionLeaseAuthority
from app.workforce.status import WorkerStatus


@dataclass(frozen=True)
class SuccessorOperationSpec:
    name: str
    objective: str
    workflow: str
    required_capability: str | None
    idempotency_key: str
    payload: dict


class OperationActivationState(str, Enum):
    """Whether deterministic activation created or found an operation."""

    CREATED = "CREATED"
    EXISTING_ACTIONABLE = "EXISTING_ACTIONABLE"
    EXISTING_TERMINAL = "EXISTING_TERMINAL"


@dataclass(frozen=True)
class SuccessorOperation:
    spec: SuccessorOperationSpec
    mission_id: str
    mission_name: str
    worker_name: str | None
    execution_id: int | None
    authority: ExecutionLeaseAuthority | None
    state: OperationActivationState


class DurableOperationActivationService:
    """Prepares an active Mission/Worker/Execution without owning the transaction."""

    def __init__(self, db):
        self.db = db

    def _existing_operation(self, spec, mission):
        terminal = mission.status in {
            MissionStatus.COMPLETED.value,
            MissionStatus.FAILED.value,
        }
        query = self.db.query(Execution).filter(Execution.mission_id == mission.id)
        if not terminal:
            query = query.filter(Execution.status.in_(("RUNNING", "RETRYING")))
        execution = query.order_by(Execution.id.desc()).first()
        authority = None
        if execution is not None and execution.lease_owner is not None:
            authority = ExecutionLeaseAuthority(
                execution.id,
                execution.lease_owner,
                execution.lease_generation,
            )
        return SuccessorOperation(
            spec,
            mission.id,
            mission.name,
            mission.current_worker_name,
            execution.id if execution is not None else None,
            authority,
            (
                OperationActivationState.EXISTING_TERMINAL
                if terminal
                else OperationActivationState.EXISTING_ACTIONABLE
            ),
        )

    def activate(self, spec: SuccessorOperationSpec, preferred_worker_name: str | None = None):
        missions, workers, executions = MissionRepository(self.db), WorkerRepository(self.db), ExecutionRepository(self.db)
        existing = missions.get_by_idempotency_key(spec.idempotency_key)
        if existing is not None:
            return self._existing_operation(spec, existing)
        mission = missions.create(str(uuid4()), spec.name, spec.objective, spec.workflow, input_data=spec.payload, required_capability=spec.required_capability, idempotency_key=spec.idempotency_key, commit=False)
        candidates = ([workers.get_by_name(preferred_worker_name)] if preferred_worker_name else []) + workers.list_online()
        worker = next((candidate for candidate in candidates if candidate and candidate.status == WorkerStatus.ONLINE.value and (not spec.required_capability or spec.required_capability in (candidate.capabilities or [])) and workers.claim(candidate.name, mission.id, commit=False)), None)
        if worker is None:
            raise RuntimeError("no eligible worker is available for durable operation activation")
        mission.status = MissionStatus.RUNNING.value; mission.current_worker_name = worker.name
        execution = executions.create(spec.workflow, "RUNNING", mission.id, mission.name, worker.name, input_data=json.dumps(spec.payload), commit=False)
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        if not executions.acquire_lease(authority, settings.EXECUTION_LEASE_SECONDS, commit=False):
            raise RuntimeError("operation execution lease could not be acquired")
        return SuccessorOperation(
            spec,
            mission.id,
            mission.name,
            worker.name,
            execution.id,
            authority,
            OperationActivationState.CREATED,
        )
