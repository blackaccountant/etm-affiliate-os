"""B.3A proofs for the audience workflow's frozen generic retry boundary."""

from copy import deepcopy
from datetime import datetime, timezone
import socket

import pytest

from app.models.audience import AudienceSignal, AudienceSignalEvidence
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.audience_repository import AudienceRepository
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.repositories.worker_repository import WorkerRepository
from app.retry.failure_classifier import FailureClassifier
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_extraction_mission_launch_service import AudienceSignalExtractionMissionLaunchService
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.task_queue.task import Task
from app.executor.executor import TaskExecutor
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workflows.audience.audience_signal_extraction_workflow import AudienceSignalExtractionWorkflow


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("B.3A must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def launch(factory):
    db = factory()
    try:
        foundation = AudienceFoundationService(db)
        observation = foundation.ingest_observation(
            research_run_id=None, subject_id=None, source_namespace="retry-test", source_type="MANUAL",
            external_observation_id=None, source_reference="retry-observation",
            observed_at=datetime.now(timezone.utc), normalized_fact={"event": "pricing"},
        )
        foundation.record_evidence(
            observation_id=observation.id, source_reference="retry-evidence",
            normalized_representation={"event": "comparison"},
        )
        WorkerRepository(db).create("Research Agent", "AI Agent", ["audience_signal_extraction"], WorkerStatus.ONLINE)
        db.commit()
        result = AudienceSignalExtractionMissionLaunchService(factory).launch(observation.id)
        execution = db.query(Execution).filter_by(mission_id=result.mission_id).one()
        return result, execution.id, execution.lease_owner, execution.lease_generation
    finally:
        db.close()


class Engine:
    def __init__(self, workflow):
        self.workflow = workflow

    def run(self, workflow_name, payload):
        return self.workflow.execute(payload)


def run_attempt(factory, launched, execution_id, owner, generation, workflow):
    db = factory()
    try:
        mission_name = db.get(MissionRecord, launched.mission_id).name
    finally:
        db.close()
    task = Task("audience_signal_extract", {"audience_research_run_id": launched.audience_research_run_id})
    task.assign_worker(type("WorkerInfo", (), {"name": "Research Agent"})())
    executor = TaskExecutor()
    executor.engine = Engine(workflow)
    return ExecutionAttemptRunner(factory, executor, workforce=WorkforceManager(load_defaults=True)).execute(
        execution_id=execution_id, mission_id=launched.mission_id, mission_name=mission_name,
        worker_name="Research Agent", task=task,
        authority=ExecutionLeaseAuthority(execution_id, owner, generation),
    )


def research_metadata(factory, run_id):
    db = factory()
    try:
        return deepcopy(AudienceRepository(db).research_run(run_id).metadata_json)
    finally:
        db.close()


def test_permanent_snapshot_failure_is_terminal_not_retryable(db_session_factory):
    launched, execution_id, owner, generation = launch(db_session_factory)
    db = db_session_factory()
    try:
        run = AudienceRepository(db).research_run(launched.audience_research_run_id)
        metadata = deepcopy(run.metadata_json)
        metadata["input_fingerprint"] = "f" * 64
        run.metadata_json = metadata
        db.commit()
    finally:
        db.close()
    metadata_before = research_metadata(db_session_factory, launched.audience_research_run_id)
    outcome = run_attempt(db_session_factory, launched, execution_id, owner, generation,
                          AudienceSignalExtractionWorkflow(session_factory=db_session_factory))
    db = db_session_factory()
    try:
        execution = db.get(Execution, execution_id)
        mission = db.get(MissionRecord, launched.mission_id)
        assert outcome.lifecycle_status == "FAILED"
        assert execution.status == mission.status == "FAILED"
        assert FailureClassifier().classify(execution.error)["retryable"] is False
        assert execution.next_retry_at is None
        assert db.get(Worker, "Research Agent").status == "ONLINE"
        assert AudienceRepository(db).research_run(launched.audience_research_run_id).metadata_json == metadata_before
    finally:
        db.close()


def test_technical_failure_surfaces_with_rollback_and_session_close(db_session_factory, monkeypatch):
    launched, execution_id, owner, generation = launch(db_session_factory)
    metadata_before = research_metadata(db_session_factory, launched.audience_research_run_id)
    original = AudienceRepository.research_run

    def technical_failure(self, run_id):
        raise RuntimeError("network failure")

    monkeypatch.setattr(AudienceRepository, "research_run", technical_failure)
    sessions = []

    class TrackedSession:
        def __init__(self):
            self.inner = db_session_factory()
            self.closed = False
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True
            self.inner.rollback()

        def close(self):
            self.closed = True
            self.inner.close()

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def factory():
        session = TrackedSession()
        sessions.append(session)
        return session

    workflow = AudienceSignalExtractionWorkflow(session_factory=factory)
    authority = ExecutionLeaseAuthority(execution_id, owner, generation)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        with pytest.raises(RuntimeError, match="network failure") as error:
            workflow.execute({"audience_research_run_id": launched.audience_research_run_id})
    assert FailureClassifier().classify(error.value) == {"failure_type": "NETWORK", "retryable": True}
    assert len(sessions) == 1 and sessions[0].rolled_back and sessions[0].closed
    monkeypatch.setattr(AudienceRepository, "research_run", original)
    db = db_session_factory()
    try:
        assert db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
        assert AudienceRepository(db).research_run(launched.audience_research_run_id).metadata_json == metadata_before
    finally:
        db.close()


def test_technical_failure_enters_frozen_generic_retry_path(db_session_factory, monkeypatch):
    launched, execution_id, owner, generation = launch(db_session_factory)
    original = AudienceRepository.research_run
    calls = []

    def fail_once(self, run_id):
        if not calls:
            calls.append(run_id)
            raise RuntimeError("network failure")
        return original(self, run_id)

    monkeypatch.setattr(AudienceRepository, "research_run", fail_once)
    outcome = run_attempt(db_session_factory, launched, execution_id, owner, generation,
                          AudienceSignalExtractionWorkflow(session_factory=db_session_factory))
    db = db_session_factory()
    try:
        execution = db.get(Execution, execution_id)
        mission = db.get(MissionRecord, launched.mission_id)
        worker = db.get(Worker, "Research Agent")
        assert calls and outcome.lifecycle_status == "QUEUED"
        assert execution.status == "QUEUED" and mission.status == "RETRY_WAIT"
        assert execution.error == "network failure"
        assert FailureClassifier().classify(execution.error) == {"failure_type": "NETWORK", "retryable": True}
        assert execution.next_retry_at is not None
        assert worker.status == "BUSY" and worker.current_mission_id == mission.id
        assert execution.lease_owner is None and execution.lease_expires_at is None
        assert execution.lease_generation == generation
    finally:
        db.close()


def test_post_flush_technical_failure_rolls_back_all_signal_writes(db_session_factory, monkeypatch):
    launched, execution_id, owner, generation = launch(db_session_factory)
    original = __import__("app.services.audience_signal_service", fromlist=["AudienceSignalService"]).AudienceSignalService.persist
    calls = []

    def fail_after_first(self, candidate, *, subject_id=None):
        if calls:
            raise RuntimeError("network failure")
        calls.append(candidate.signal_type)
        return original(self, candidate, subject_id=subject_id)

    monkeypatch.setattr("app.workflows.audience.audience_signal_extraction_workflow.AudienceSignalService.persist", fail_after_first)

    def transaction_factory():
        session = db_session_factory()
        session.query(Execution).filter(Execution.id == execution_id).update(
            {Execution.lease_generation: Execution.lease_generation}, synchronize_session=False,
        )
        return session

    authority = ExecutionLeaseAuthority(execution_id, owner, generation)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        with pytest.raises(RuntimeError, match="network failure"):
            AudienceSignalExtractionWorkflow(session_factory=transaction_factory).execute(
                {"audience_research_run_id": launched.audience_research_run_id}
            )
    db = db_session_factory()
    try:
        assert calls
        assert db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
    finally:
        db.close()


def test_lease_loss_propagates_without_workflow_conversion(db_session_factory):
    launched, execution_id, owner, generation = launch(db_session_factory)
    db = db_session_factory()
    try:
        db.get(Execution, execution_id).lease_generation += 1
        db.commit()
    finally:
        db.close()
    authority = ExecutionLeaseAuthority(execution_id, owner, generation)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        with pytest.raises(ExecutionLeaseLostError):
            AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute(
                {"audience_research_run_id": launched.audience_research_run_id}
            )
