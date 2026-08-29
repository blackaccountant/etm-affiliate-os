"""Synchronous workflow invocation and normalized task outcome handling.

Durable active-execution finalization belongs exclusively to
``ExecutionAttemptRunner`` and ``OwnedExecutionLifecycleCoordinator``.
"""

from dataclasses import asdict, is_dataclass
import json
from time import perf_counter

from app.memory.memory_bus import MemoryBus
from app.retry.failure_classifier import FailureClassifier
from app.retry.retry_policy import RetryPolicy
from app.workflow_engine.workflow_engine import WorkflowEngine


class TaskExecutor:
    """Invoke a workflow and update only the in-memory task/runtime projection."""

    def __init__(self, runtime=None, execution_service=None):
        # ``execution_service`` remains accepted for compatibility with retry
        # construction sites, but is intentionally not a lifecycle authority.
        self.engine = WorkflowEngine()
        self.memory = MemoryBus()
        self.runtime = runtime
        self.execution_service = execution_service
        self.workforce = None
        self.retry_policy = RetryPolicy()
        self.failure_classifier = FailureClassifier()
        if runtime:
            self.workforce = getattr(runtime, "workforce", None)

    def _serialize_result(self, result):
        if is_dataclass(result):
            return json.dumps(asdict(result), default=str)
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), default=str)
        if hasattr(result, "dict"):
            return json.dumps(result.dict(), default=str)
        if isinstance(result, dict):
            return json.dumps(result, default=str)
        return json.dumps({"result": str(result)}, default=str)

    @staticmethod
    def _workflow_succeeded(result):
        success = getattr(result, "success", None)
        if success is None and isinstance(result, dict):
            success = result.get("success")
        return True if success is None else bool(success)

    @staticmethod
    def _workflow_error_text(result, workflow_name):
        errors = getattr(result, "errors", None)
        if errors is None and isinstance(result, dict):
            errors = result.get("errors", [])
        if errors:
            return "; ".join(str(error) for error in errors)
        return f"Workflow '{workflow_name}' reported failure."

    @staticmethod
    def _worker_name(task):
        worker = getattr(task, "worker", None)
        if worker is None:
            return None
        return worker.name if hasattr(worker, "name") else str(worker)

    def _runtime_event(self, workflow_name, worker_name, status, event_type, **metadata):
        if not self.runtime:
            return
        self.runtime.update_execution_status(workflow_name, status)
        self.runtime.record_event(
            f"{workflow_name} {status.title()}", event_type=event_type,
            metadata={"workflow": workflow_name, "worker": worker_name, **metadata},
        )

    def execute(self, task):
        """Run a workflow without writing Execution, Mission, or Worker rows."""
        task._execution_error = None
        started = perf_counter()
        workflow_name = task.workflow_name
        worker_name = self._worker_name(task)
        if self.runtime:
            self.runtime.record_execution({
                "workflow": workflow_name, "worker": worker_name,
                "status": "CREATED", "duration": 0.0,
            })
            self._runtime_event(workflow_name, worker_name, "RUNNING", "RUNNING")

        try:
            result = self.engine.run(workflow_name=workflow_name, payload=task.payload)
            duration = perf_counter() - started
            if self._workflow_succeeded(result):
                task.mark_completed()
                self._runtime_event(workflow_name, worker_name, "COMPLETED", "SUCCESS", duration=duration)
                self.memory.store("last_execution", {
                    "workflow": workflow_name, "worker": worker_name,
                    "status": "COMPLETED", "duration": duration,
                })
                return result

            error = self._workflow_error_text(result, workflow_name)
            failure = self.failure_classifier.classify(error)
            if failure.get("retryable", False) and self.retry_policy.execute_retry(task):
                next_retry_at = self.retry_policy.calculate_next_retry(task)
                self._runtime_event(
                    workflow_name, worker_name, "RETRYING", "RETRY",
                    retry_count=task.retry_count,
                    next_retry_at=next_retry_at.isoformat() if next_retry_at else None,
                    failure_type=failure.get("failure_type"), error=error,
                )
                self.memory.store("last_execution", {
                    "workflow": workflow_name, "worker": worker_name,
                    "status": "RETRYING", "retry_count": task.retry_count,
                    "duration": duration, "failure_type": failure.get("failure_type"),
                    "error": error,
                })
                return result

            task.mark_failed()
            self._runtime_event(
                workflow_name, worker_name, "FAILED", "ERROR", duration=duration,
                retry_count=task.retry_count, failure_type=failure.get("failure_type"), error=error,
            )
            self.memory.store("last_execution", {
                "workflow": workflow_name, "worker": worker_name, "status": "FAILED",
                "duration": duration, "retry_count": task.retry_count,
                "failure_type": failure.get("failure_type"), "error": error,
            })
            return result
        except Exception as exc:
            duration = perf_counter() - started
            task._execution_error = str(exc)
            if self.retry_policy.execute_retry(task):
                next_retry_at = self.retry_policy.calculate_next_retry(task)
                self._runtime_event(
                    workflow_name, worker_name, "RETRYING", "RETRY",
                    retry_count=task.retry_count,
                    next_retry_at=next_retry_at.isoformat() if next_retry_at else None,
                    error=str(exc),
                )
                self.memory.store("last_execution", {
                    "workflow": workflow_name, "worker": worker_name,
                    "status": "RETRYING", "retry_count": task.retry_count,
                    "duration": duration, "error": str(exc),
                })
                return None
            task.mark_failed()
            self._runtime_event(
                workflow_name, worker_name, "FAILED", "ERROR", duration=duration,
                retry_count=task.retry_count, error=str(exc),
            )
            self.memory.store("last_execution", {
                "workflow": workflow_name, "worker": worker_name, "status": "FAILED",
                "duration": duration, "retry_count": task.retry_count, "error": str(exc),
            })
            raise
