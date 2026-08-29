"""Durable initial mission orchestration."""

import json
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass

from app.database.session import SessionLocal
from app.executor.executor import TaskExecutor
from app.mission.mission import Mission
from app.mission.mission_result import MissionResult
from app.mission.registry import MissionRegistry
from app.mission.result_registry import ResultRegistry
from app.mission.status import MissionStatus, validate_mission_transition
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.scheduler.scheduler import Scheduler
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.workforce.manager import WorkforceManager


class MissionManager:
    def __init__(self, workforce=None, runtime=None, session_factory=None):
        self.registry = MissionRegistry()
        self.results = ResultRegistry()
        self.scheduler = Scheduler()
        self.runtime = runtime
        self.executor = TaskExecutor(runtime=runtime)
        self.workforce = workforce if workforce is not None else WorkforceManager()
        self.session_factory = session_factory if session_factory is not None else SessionLocal

    @contextmanager
    def _operation(self):
        db = self.session_factory()
        try:
            yield db
        except Exception:
            rollback = getattr(db, "rollback", None)
            if rollback:
                rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _normalize(value):
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        if isinstance(value, dict):
            return value
        if hasattr(value, "__dict__"):
            return value.__dict__
        return {"result": str(value)}

    @staticmethod
    def _success(result):
        return result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)

    @staticmethod
    def _errors(result):
        return result.get("errors", []) if isinstance(result, dict) else getattr(result, "errors", [])

    def _persisted_mission(self, repository, mission):
        record = repository.create(
            mission_id=mission.id, name=mission.name, objective=mission.objective,
            workflow_name=mission.workflow, input_data=mission.metadata,
            required_capability=mission.required_capability,
            idempotency_key=getattr(mission, "idempotency_key", None),
        )
        if record.id == mission.id:
            mission._idempotent_existing = False
            return mission
        restored = Mission.from_record(record)
        restored.idempotency_key = record.idempotency_key
        restored._idempotent_existing = True
        return restored

    def create_mission(self, name, objective, workflow, metadata=None,
                       required_capability=None, idempotency_key=None):
        mission = Mission(name, objective, workflow, metadata, required_capability)
        mission.idempotency_key = idempotency_key
        with self._operation() as db:
            mission = self._persisted_mission(MissionRepository(db), mission)
        self.registry.add(mission)
        return mission

    def _transition(self, mission, repository, status, **kwargs):
        target_status = MissionStatus(status)
        validate_mission_transition(mission.status, target_status)
        record = repository.update_status(mission.id, target_status, **kwargs)
        if record is None:
            raise RuntimeError("Durable mission record disappeared during launch")
        mission.status = target_status
        mission.updated_at = record.updated_at

    def execute(self, mission, worker=None):
        if worker is None:
            return None
        with self._operation() as db:
            missions, executions = MissionRepository(db), ExecutionRepository(db)
            self._transition(mission, missions, MissionStatus.RUNNING, current_worker_name=worker.name)
            task = self.scheduler.schedule(mission.workflow, dict(mission.metadata))
            task = self.scheduler.next_task()  # Consume the directly executed task.
            task.assign_worker(worker)
            execution = executions.create(mission.workflow, "RUNNING", mission.id, mission.name,
                worker.name, input_data=json.dumps(mission.metadata, default=str),
                max_retries=task.max_retries)
            execution_id = execution.id
        attempt = ExecutionAttemptRunner(
            self.session_factory, self.executor, workforce=self.workforce,
        ).execute(
            execution_id=execution_id, mission_id=mission.id, mission_name=mission.name,
            worker_name=worker.name, task=task,
        )
        if attempt.ownership_lost:
            return MissionResult(mission.id, False, attempt.result, "Execution lease ownership was lost.")
        mission.status = (
            MissionStatus.RETRY_WAIT if attempt.lifecycle_status == "QUEUED"
            else MissionStatus(attempt.lifecycle_status)
        )
        success = attempt.lifecycle_status == "COMPLETED"
        error = str(attempt.error) if attempt.error else None
        if self.runtime and getattr(self.runtime, "memory", None):
            self.runtime.memory.store("latest_mission_result", {
                "mission_id": mission.id,
                "mission": mission.name,
                "workflow": mission.workflow,
                "worker": worker.name,
                "success": success,
                "status": attempt.lifecycle_status,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "data": attempt.result,
            })
        mission_result = MissionResult(mission.id, success, attempt.result, error)
        self.results.add(mission_result)
        if attempt.error is not None:
            raise attempt.error
        return mission_result

    def resume_recovered_mission(self, recovered):
        """Dispatch one committed replacement without creating a Mission.

        Recovery context is intentionally injected here, after the durable
        mission payload is read, rather than accepted from caller input.
        """
        with self._operation() as db:
            missions = MissionRepository(db)
            workers = WorkerRepository(db)
            executions = ExecutionRepository(db)
            mission = missions.get_by_id(recovered.mission_id)
            execution = executions.get_by_id(recovered.replacement_execution_id)
            durable_worker = workers.get_by_name(recovered.worker_name)
            if (
                mission is None
                or mission.status != MissionStatus.RUNNING.value
                or execution is None
                or execution.mission_id != mission.id
                or execution.workflow_name != mission.workflow_name
                or durable_worker is None
                or durable_worker.current_mission_id != mission.id
            ):
                raise RuntimeError("recovered execution no longer has durable mission ownership")
            try:
                payload = json.loads(mission.input_data or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {"input_data": mission.input_data}
            if not isinstance(payload, dict):
                payload = {"input_data": payload}
            payload = dict(payload)
            payload["execution_recovery"] = True
            payload["recovered_execution_id"] = recovered.abandoned_execution_id
            task = self.scheduler.schedule(execution.workflow_name, payload)
            task = self.scheduler.next_task()
            task.retry_count = execution.retry_count
            task.max_retries = execution.max_retries
            task.assign_worker(self.workforce.sync_from_durable(durable_worker, mission.name))

        attempt = ExecutionAttemptRunner(
            self.session_factory, self.executor, workforce=self.workforce,
        ).execute(
            execution_id=recovered.replacement_execution_id,
            mission_id=recovered.mission_id, mission_name=recovered.mission_name,
            worker_name=recovered.worker_name, task=task,
            authority=recovered.authority,
        )
        if attempt.ownership_lost:
            return MissionResult(recovered.mission_id, False, attempt.result, "Execution lease ownership was lost.")
        result = MissionResult(
            recovered.mission_id, attempt.lifecycle_status == "COMPLETED",
            attempt.result, str(attempt.error) if attempt.error else None,
        )
        self.results.add(result)
        if attempt.error is not None:
            raise attempt.error
        return result

    def recover_expired_execution(self, execution_id):
        """Recover one durable attempt and dispatch its replacement exactly once."""
        recovery = RunningExecutionRecoveryService(self.session_factory)
        return recovery.recover_and_dispatch(execution_id, self.resume_recovered_mission)

    def launch(self, name, objective, workflow, metadata=None, required_capability=None,
               idempotency_key=None):
        mission = self.create_mission(name, objective, workflow, metadata, required_capability, idempotency_key)
        if idempotency_key and getattr(mission, "_idempotent_existing", False):
            return {"mission": mission, "worker": None, "result": None}
        with self._operation() as db:
            missions, workers = MissionRepository(db), WorkerRepository(db)
            worker = self.workforce.claim_durable(
                mission.name, mission.required_capability,
                lambda candidate: (workers.ensure(candidate) and workers.claim(candidate.name, mission.id)),
            )
            if worker is None:
                self._transition(mission, missions, MissionStatus.WAITING_FOR_WORKER)
                return {"mission": mission, "worker": None, "result": None}
            self._transition(mission, missions, MissionStatus.ASSIGNED, current_worker_name=worker.name)
        result = self.execute(mission, worker)
        return {"mission": mission, "worker": worker, "result": result}

    def get_mission(self, mission_id):
        return self.registry.get(mission_id)

    def get_results(self, mission_id):
        return self.results.get_by_mission(mission_id)

    def missions(self):
        return self.registry.all()

    def clear(self):
        self.registry.clear()
        self.results.clear()
