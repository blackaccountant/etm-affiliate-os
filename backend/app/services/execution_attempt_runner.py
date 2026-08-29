"""Lease-aware runtime for one synchronous execution attempt."""

from dataclasses import dataclass
import json
from time import perf_counter

from app.core.config import settings
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.services.execution_lease import ExecutionLeaseAuthority, ExecutionLeaseHeartbeat
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.execution_runtime_context import (
    ExecutionRuntimeContext,
    activate_execution_runtime_context,
)


@dataclass
class ExecutionAttemptResult:
    result: object
    error: Exception | None
    lifecycle_status: str | None
    ownership_lost: bool = False


class ExecutionAttemptRunner:
    """Own lease acquisition, heartbeat lifetime, workflow call, and finalization."""

    def __init__(self, session_factory, executor, workforce=None,
                 lease_seconds=None, heartbeat_seconds=None):
        self.session_factory = session_factory
        self.executor = executor
        self.workforce = workforce
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    def _authority(self, execution):
        return ExecutionLeaseAuthority.fresh(
            execution.id, generation=(execution.lease_generation or 0) + 1,
        )

    def execute(self, *, execution_id, mission_id, mission_name, worker_name, task,
                before_workflow=None, authority=None):
        db = self.session_factory()
        heartbeat = None
        try:
            executions = ExecutionRepository(db)
            execution = executions.get_by_id(execution_id)
            if execution is None:
                raise RuntimeError("Execution disappeared before attempt start")
            supplied_authority = authority is not None
            authority = authority or self._authority(execution)
            if authority.execution_id != execution.id:
                raise ValueError("execution authority does not match the requested execution")
            if supplied_authority:
                if authority.lease_owner != execution.lease_owner or authority.lease_generation != execution.lease_generation:
                    return ExecutionAttemptResult(None, None, None, ownership_lost=True)
            else:
                if not executions.acquire_lease(authority, self.lease_seconds or settings.EXECUTION_LEASE_SECONDS):
                    return ExecutionAttemptResult(None, None, None, ownership_lost=True)
            if before_workflow is not None:
                try:
                    before_workflow()
                except Exception:
                    # No workflow has started.  Return the claimed retry to its
                    # active-but-unleased state so a later recovery can decide
                    # how to proceed without leaving phantom authority behind.
                    db.query(type(execution)).filter(
                        type(execution).id == authority.execution_id,
                        type(execution).lease_owner == authority.lease_owner,
                        type(execution).lease_generation == authority.lease_generation,
                    ).update({
                        type(execution).lease_owner: None,
                        type(execution).lease_expires_at: None,
                    }, synchronize_session=False)
                    db.commit()
                    raise

            heartbeat = ExecutionLeaseHeartbeat(
                self.session_factory, authority,
                lease_seconds=self.lease_seconds,
                heartbeat_seconds=self.heartbeat_seconds,
            ).start()
            started = perf_counter()
            result = None
            original_error = None
            try:
                runtime_context = ExecutionRuntimeContext(
                    authority=authority,
                    mission_id=mission_id,
                    is_recovery=supplied_authority,
                )
                with activate_execution_runtime_context(runtime_context):
                    result = self.executor.execute(task)
            except Exception as exc:  # TaskExecutor normalized task retry state first.
                original_error = exc
            duration = perf_counter() - started

            if original_error is None:
                success_method = getattr(self.executor, "_workflow_succeeded", None)
                success = success_method(result) if success_method else self._workflow_succeeded(result)
                if result is None and getattr(task, "_execution_error", None):
                    success = False
                    error = task._execution_error
                else:
                    error_method = getattr(self.executor, "_workflow_error_text", None)
                    error = None if success else (
                        error_method(result, task.workflow_name) if error_method
                        else self._workflow_error_text(result, task.workflow_name)
                    )
            else:
                success = False
                error = str(original_error)
            classifier = getattr(self.executor, "failure_classifier", None)
            failure = classifier.classify(error) if error and classifier else {}
            retrying = (
                not success and task.status == "QUEUED"
                and 0 < task.retry_count < task.max_retries
            )
            payload = self._normalize(result, error)
            serializer = getattr(self.executor, "_serialize_result", None)
            serialized = serializer(payload) if serializer else json.dumps(payload, default=str)
            lifecycle = OwnedExecutionLifecycleCoordinator(db, self.workforce)
            try:
                # A legacy retry test double that does not implement the
                # TaskExecutor normalization contract must not be interpreted
                # as an authoritative completion.
                if not hasattr(self.executor, "_workflow_succeeded"):
                    final = lifecycle.schedule_retry(
                        authority, mission_id=mission_id, mission_name=mission_name,
                        worker_name=worker_name, result_data=serialized,
                        result_payload=payload, retry_count=task.retry_count,
                        max_retries=task.max_retries,
                        next_retry_at=self._now(), error="Retry executor did not normalize outcome",
                        failure_type=None,
                    )
                elif success:
                    final = lifecycle.complete(
                        authority, mission_id=mission_id, mission_name=mission_name,
                        worker_name=worker_name, duration=duration,
                        result_data=serialized, result_payload=payload,
                    )
                elif retrying:
                    final = lifecycle.schedule_retry(
                        authority, mission_id=mission_id, mission_name=mission_name,
                        worker_name=worker_name, result_data=serialized,
                        result_payload=payload, retry_count=task.retry_count,
                        max_retries=task.max_retries,
                        next_retry_at=self.executor.retry_policy.calculate_next_retry(task),
                        error=error, failure_type=failure.get("failure_type"),
                    )
                else:
                    final = lifecycle.fail(
                        authority, mission_id=mission_id, mission_name=mission_name,
                        worker_name=worker_name, duration=duration,
                        result_data=serialized, result_payload=payload, error=error,
                        failure_type=failure.get("failure_type"), retry_count=task.retry_count,
                    )
            except ExecutionLeaseLostError:
                return ExecutionAttemptResult(result, original_error, None, ownership_lost=True)
            return ExecutionAttemptResult(result, original_error, final.status)
        finally:
            if heartbeat is not None:
                heartbeat.stop()
            db.close()

    @staticmethod
    def _normalize(result, error):
        if result is None:
            return {"success": False, "errors": [error or "Mission execution failed."]}
        if isinstance(result, dict):
            return result
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        if hasattr(result, "__dict__"):
            return dict(result.__dict__)
        return {"result": str(result)}

    @staticmethod
    def _workflow_succeeded(result):
        return result.get("success", True) if isinstance(result, dict) else bool(getattr(result, "success", True))

    @staticmethod
    def _workflow_error_text(result, workflow_name):
        errors = result.get("errors", []) if isinstance(result, dict) else getattr(result, "errors", [])
        return "; ".join(map(str, errors)) if errors else f"Workflow '{workflow_name}' reported failure."

    @staticmethod
    def _now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)
