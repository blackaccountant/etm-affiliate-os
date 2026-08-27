import json
import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import DateTime

from app.executor.executor import TaskExecutor
from app.models.execution import Execution
from app.repositories.execution_repository import ExecutionRepository
from app.retry.failure_classifier import FailureClassifier
from app.retry.retry_manager import RetryManager
from app.retry.retry_policy import RetryPolicy
from app.retry.retry_scanner import RetryScanner
from app.retry.retry_worker import RetryWorker
from app.scheduler.scheduler import Scheduler
from app.system import runtime as runtime_module
from app.task_queue.task import Task


class FakeWorkflowEngine:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, workflow_name, payload):
        self.calls.append((workflow_name, payload))
        return self.result


class FakePersistedExecution:
    def __init__(self, execution_id=101):
        self.id = execution_id
        self.status = "RETRYING"
        self.retry_count = 0
        self.max_retries = 3
        self.next_retry_at = datetime.now(timezone.utc)
        self.failure_type = "NETWORK"
        self.error = "previous failure"
        self.result_data = None


class FakeExecutionService:
    def __init__(self, execution):
        self.execution = execution
        self.complete_calls = []
        self.schedule_retry_calls = []
        self.fail_calls = []

    def get_by_id(self, execution_id):
        return self.execution if execution_id == self.execution.id else None

    def complete(self, execution, duration, result_data):
        self.complete_calls.append((execution, duration, result_data))
        execution.status = "COMPLETED"
        execution.result_data = result_data
        execution.next_retry_at = None
        execution.failure_type = None
        execution.error = None
        return execution

    def schedule_retry(
        self,
        execution,
        retry_count,
        max_retries,
        next_retry_at,
        failure_type,
        error,
    ):
        self.schedule_retry_calls.append(
            {
                "execution": execution,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "next_retry_at": next_retry_at,
                "failure_type": failure_type,
                "error": error,
            }
        )
        execution.status = "QUEUED"
        execution.retry_count = retry_count
        execution.max_retries = max_retries
        execution.next_retry_at = next_retry_at
        execution.failure_type = failure_type
        execution.error = error
        return execution

    def fail(self, execution, error, failure_type, duration, retry_count):
        self.fail_calls.append(
            {
                "execution": execution,
                "error": error,
                "failure_type": failure_type,
                "duration": duration,
                "retry_count": retry_count,
            }
        )
        execution.status = "FAILED"
        execution.error = error
        execution.failure_type = failure_type
        execution.retry_count = retry_count
        execution.next_retry_at = None
        return execution


def test_utc_contract_for_execution_and_retry_timestamps():
    for name in ("started_at", "completed_at", "next_retry_at"):
        column = Execution.__table__.columns[name]
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True

    now = ExecutionRepository._utc_now()
    retry_at = RetryPolicy().calculate_next_retry(Task("workflow", {}))

    assert now.tzinfo is timezone.utc
    assert retry_at.tzinfo is timezone.utc


@pytest.mark.parametrize(
    ("message", "retryable", "failure_type"),
    [
        ("Unable to fetch website.", True, "NETWORK"),
        ("connection refused", True, "NETWORK"),
        ("request timeout", True, "TIMEOUT"),
        ("503 Service Unavailable", True, None),
        ("invalid API key", False, "VALIDATION"),
        ("permission denied", False, "PERMISSION"),
        ("an unrecognized failure", False, "UNKNOWN"),
    ],
)
def test_failure_classification_contract(message, retryable, failure_type):
    result = FailureClassifier().classify(message)

    assert result["retryable"] is retryable
    if failure_type is not None:
        assert result["failure_type"] == failure_type


def test_retry_scanner_restores_durable_payload_and_syncs_task_state():
    class RetryExecution:
        id = 42
        workflow_name = "affiliate_discovery"
        mission_id = "mission-7"
        retry_count = 1
        max_retries = 3
        failure_type = "NETWORK"
        status = "QUEUED"
        input_data = json.dumps(
            {"url": "https://example.invalid", "nested": {"value": True}}
        )

    class ScannerService:
        def __init__(self, execution):
            self.execution = execution
            self.limits = []

        def get_retry_queue(self, limit):
            self.limits.append(limit)
            return [self.execution]

        def claim_retry(self, execution):
            execution.status = "RETRYING"
            return execution

    execution = RetryExecution()
    service = ScannerService(execution)
    scheduler = Scheduler()

    tasks = RetryScanner(service, scheduler).scan_once(limit=4)

    assert service.limits == [4]
    assert execution.status == "RETRYING"
    assert len(tasks) == 1
    task = tasks[0]
    assert task.payload == {
        "url": "https://example.invalid",
        "nested": {"value": True},
        "mission_id": "mission-7",
        "execution_id": 42,
        "retry_count": 1,
        "max_retries": 3,
        "failure_type": "NETWORK",
    }
    assert task.retry_count == 1
    assert task.max_retries == 3


def test_executor_success_persists_result_and_clears_retry_state():
    execution = FakePersistedExecution()
    service = FakeExecutionService(execution)
    result = {
        "success": True,
        "workflow": "affiliate_discovery",
        "data": {"test": True},
        "errors": [],
    }
    task = Task("affiliate_discovery", {"execution_id": execution.id})
    executor = TaskExecutor(execution_service=service)
    executor.engine = FakeWorkflowEngine(result)

    returned = executor.execute(task)

    assert returned == result
    assert task.status == "COMPLETED"
    assert len(service.complete_calls) == 1
    assert json.loads(execution.result_data) == result
    assert execution.status == "COMPLETED"
    assert execution.next_retry_at is None
    assert execution.failure_type is None
    assert execution.error is None


def test_retryable_workflow_failure_is_queued_with_persisted_metadata():
    execution = FakePersistedExecution()
    service = FakeExecutionService(execution)
    result = {"success": False, "errors": ["Unable to fetch website."]}
    task = Task("affiliate_discovery", {"execution_id": execution.id})
    executor = TaskExecutor(execution_service=service)
    executor.engine = FakeWorkflowEngine(result)

    returned = executor.execute(task)

    assert returned == result
    assert task.status == "QUEUED"
    assert task.retry_count == 1
    assert len(service.schedule_retry_calls) == 1
    assert execution.status == "QUEUED"
    assert execution.failure_type == "NETWORK"
    assert execution.error == "Unable to fetch website."
    assert json.loads(execution.result_data) == result
    assert execution.next_retry_at.tzinfo is timezone.utc
    assert execution.status != "COMPLETED"


def test_retry_exhaustion_persists_final_failure_and_result():
    execution = FakePersistedExecution()
    execution.retry_count = 2
    service = FakeExecutionService(execution)
    result = {"success": False, "errors": ["Unable to fetch website."]}
    task = Task("affiliate_discovery", {"execution_id": execution.id})
    task.retry_count = 2
    task.max_retries = 3
    executor = TaskExecutor(execution_service=service)
    executor.engine = FakeWorkflowEngine(result)

    returned = executor.execute(task)

    assert returned == result
    assert task.retry_count == 3
    assert task.status == "FAILED"
    assert service.schedule_retry_calls == []
    assert len(service.fail_calls) == 1
    assert execution.status == "FAILED"
    assert execution.next_retry_at is None
    assert execution.failure_type == "NETWORK"
    assert execution.error == "Unable to fetch website."
    assert json.loads(execution.result_data) == result


def test_retry_manager_cycle_processor_passes_limit_and_normalizes_result():
    limits = []

    def cycle_processor(limit):
        limits.append(limit)
        return "completed"

    manager = RetryManager(cycle_processor=cycle_processor)

    assert manager.process_once(limit=6) == ["completed"]
    assert manager.get_last_results() == ["completed"]
    assert limits == [6]


def test_retry_manager_legacy_mode_processes_each_scanned_task():
    class Scanner:
        def __init__(self):
            self.limits = []

        def scan_once(self, limit):
            self.limits.append(limit)
            return [object(), object()]

    class Worker:
        def __init__(self):
            self.calls = 0

        def process_once(self):
            self.calls += 1
            return self.calls

    scanner = Scanner()
    worker = Worker()
    manager = RetryManager(scanner=scanner, worker=worker)

    assert manager.process_once(limit=2) == [1, 2]
    assert scanner.limits == [2]
    assert worker.calls == 2


def test_runtime_creates_and_closes_one_session_per_retry_cycle(monkeypatch):
    sessions = []
    scanner_limits = []

    class Session:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        def rollback(self):
            pass

    class Repository:
        def __init__(self, db):
            self.db = db

    class Service:
        def __init__(self, repository):
            self.repository = repository

    class Scanner:
        def __init__(self, execution_service, scheduler):
            self.scheduler = scheduler

        def scan_once(self, limit):
            scanner_limits.append(limit)
            return []

    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: sessions.append(Session()) or sessions[-1])
    monkeypatch.setattr(runtime_module, "ExecutionRepository", Repository)
    monkeypatch.setattr(runtime_module, "ExecutionService", Service)
    monkeypatch.setattr(runtime_module, "RetryScanner", Scanner)

    runtime = runtime_module.RuntimeAdapter()
    assert not hasattr(runtime, "db")

    assert runtime._process_retry_cycle(limit=3) == []
    assert runtime._process_retry_cycle(limit=5) == []

    assert scanner_limits == [3, 5]
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert all(session.closed for session in sessions)


def test_retry_manager_background_lifecycle_is_safe_and_stoppable():
    cycle_started = threading.Event()

    def cycle_processor(limit):
        cycle_started.set()
        return []

    manager = RetryManager(cycle_processor=cycle_processor, poll_interval=0.1)

    assert manager.start() is True
    assert cycle_started.wait(timeout=1.0)
    assert manager.is_running() is True
    assert manager.start() is False
    assert manager.stop(timeout=1.0) is True
    assert manager.is_running() is False


def test_retry_worker_drains_queued_task_and_empty_queue_is_safe():
    class Executor:
        def __init__(self):
            self.tasks = []

        def execute(self, task):
            self.tasks.append(task)
            return {"success": True}

    scheduler = Scheduler()
    executor = Executor()
    worker = RetryWorker(scheduler, executor)
    scheduled = scheduler.schedule("affiliate_discovery", {"test": True})

    assert worker.process_once() == {"success": True}
    assert executor.tasks == [scheduled]
    assert worker.process_once() is None
