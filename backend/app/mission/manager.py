"""Durable initial mission orchestration."""

import json
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from time import perf_counter

from app.database.session import SessionLocal
from app.executor.executor import TaskExecutor
from app.mission.mission import Mission
from app.mission.mission_result import MissionResult
from app.mission.registry import MissionRegistry
from app.mission.result_registry import ResultRegistry
from app.mission.status import MissionStatus
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.failure_classifier import FailureClassifier
from app.scheduler.scheduler import Scheduler
from app.workforce.manager import WorkforceManager


class MissionManager:
    def __init__(self, workforce=None, runtime=None, session_factory=None):
        self.registry = MissionRegistry()
        self.results = ResultRegistry()
        self.scheduler = Scheduler()
        self.runtime = runtime
        self.executor = TaskExecutor(runtime=runtime)
        self.workforce = workforce if workforce is not None else WorkforceManager()
        self.failure_classifier = FailureClassifier()
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
        mission.update_status(status)
        record = repository.update_status(mission.id, status, **kwargs)
        if record is None:
            raise RuntimeError("Durable mission record disappeared during launch")

    def _finalize(self, mission, worker, task, execution, repositories, result, duration):
        missions, workers, executions = repositories
        success = self._success(result)
        errors = self._errors(result) or []
        error = None if success else "; ".join(map(str, errors)) or "Mission execution failed."
        failure = self.failure_classifier.classify(error) if not success else {}
        retrying = (not success and task.status == "QUEUED" and task.retry_count > 0)
        payload = self._normalize(result) if result is not None else {"success": False, "error": error}
        serialized = json.dumps(payload, default=str)
        next_retry_at = None
        if success:
            executions.complete(execution, duration, serialized)
            self._transition(mission, missions, MissionStatus.COMPLETED,
                             result_data=payload, last_error=None)
            workers.release(worker.name, mission.id, success=True)
            self.workforce.release(worker.name, success=True)
        elif retrying:
            execution.result_data = serialized
            next_retry_at = self.executor.retry_policy.calculate_next_retry(task)
            executions.schedule_retry(execution, task.retry_count, task.max_retries,
                next_retry_at, failure.get("failure_type"), error)
            self._transition(mission, missions, MissionStatus.RETRY_WAIT,
                             result_data=payload, last_error=error,
                             current_worker_name=worker.name)
        else:
            execution.result_data = serialized
            executions.fail(execution, error, failure.get("failure_type"), duration, task.retry_count)
            self._transition(mission, missions, MissionStatus.FAILED,
                             result_data=payload, last_error=error)
            workers.release(worker.name, mission.id, success=False)
            self.workforce.release(worker.name, success=False)
        if self.runtime:
            self.runtime.memory.store("latest_mission_result", {
                "mission_id": mission.id,
                "mission": mission.name,
                "workflow": mission.workflow,
                "worker": worker.name,
                "success": success and not retrying,
                "status": "COMPLETED" if success else "QUEUED" if retrying else "FAILED",
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "failure_type": failure.get("failure_type"),
                "retryable": failure.get("retryable", False),
                "next_retry_at": next_retry_at,
                "data": result,
            })
        return MissionResult(mission.id, success and not retrying, result, error)

    def execute(self, mission, worker=None):
        if worker is None:
            return None
        with self._operation() as db:
            missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
            self._transition(mission, missions, MissionStatus.RUNNING, current_worker_name=worker.name)
            task = self.scheduler.schedule(mission.workflow, dict(mission.metadata))
            task = self.scheduler.next_task()  # Consume the directly executed task.
            task.assign_worker(worker)
            execution = executions.create(mission.workflow, "RUNNING", mission.id, mission.name,
                worker.name, input_data=json.dumps(mission.metadata, default=str),
                max_retries=task.max_retries)
            started = perf_counter()
            try:
                result = self.executor.execute(task)
            except Exception as exc:
                task.mark_failed()
                result = {"success": False, "errors": [str(exc)]}
                mission_result = self._finalize(mission, worker, task, execution,
                    (missions, workers, executions), result, perf_counter() - started)
                self.results.add(mission_result)
                raise
            mission_result = self._finalize(mission, worker, task, execution,
                (missions, workers, executions), result, perf_counter() - started)
            self.results.add(mission_result)
            return mission_result

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
