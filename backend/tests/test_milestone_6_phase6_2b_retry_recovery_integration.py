"""B.3C integration proofs for audience retry exhaustion and Phase 3R recovery."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import socket

import pytest

from app.models.audience import AudienceSignal, AudienceSignalEvidence
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.audience_repository import AudienceRepository
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_extraction_mission_launch_service import AudienceSignalExtractionMissionLaunchService
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.task_queue.task import Task
from app.executor.executor import TaskExecutor
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workflows.audience.audience_signal_extraction_workflow import AudienceSignalExtractionWorkflow


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def blocked(*args, **kwargs): raise AssertionError("B.3C must not access the network")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


class Engine:
    def __init__(self, workflow): self.workflow = workflow
    def run(self, workflow_name, payload): return self.workflow.execute(payload)


def launch(factory, *, event="pricing", evidence_event="comparison"):
    db = factory()
    try:
        foundation = AudienceFoundationService(db)
        observation = foundation.ingest_observation(research_run_id=None, subject_id=None,
            source_namespace="b3c", source_type="MANUAL", external_observation_id=None,
            source_reference="b3c-observation", observed_at=datetime.now(timezone.utc),
            normalized_fact={"event": event})
        foundation.record_evidence(observation_id=observation.id, source_reference="b3c-evidence",
            normalized_representation={"event": evidence_event})
        WorkerRepository(db).create("Research Agent", "AI Agent", ["audience_signal_extraction"], WorkerStatus.ONLINE)
        db.commit()
        return AudienceSignalExtractionMissionLaunchService(factory).launch(observation.id), observation.id
    finally: db.close()


def state(factory, launched):
    db = factory()
    try:
        run = AudienceRepository(db).research_run(launched.audience_research_run_id)
        mission = db.get(MissionRecord, launched.mission_id)
        execution = db.query(Execution).filter_by(mission_id=mission.id).order_by(Execution.id).first()
        return run, mission, execution, ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)
    finally: db.close()


def attempt(factory, launched, execution, authority, workflow, retry_count=0):
    task = Task("audience_signal_extract", {"audience_research_run_id": launched.audience_research_run_id})
    task.retry_count = retry_count
    task.assign_worker(type("WorkerInfo", (), {"name": "Research Agent"})())
    executor = TaskExecutor(); executor.engine = Engine(workflow)
    return ExecutionAttemptRunner(factory, executor, workforce=WorkforceManager(load_defaults=True)).execute(
        execution_id=execution.id, mission_id=launched.mission_id, mission_name="Audience signal extraction",
        worker_name="Research Agent", task=task, authority=authority,
    )


def snapshot(db):
    signals = [(row.id, row.extraction_key, row.signal_type, row.topic_slug, row.intent_stage,
                row.strength, row.confidence, row.evidence_set_fingerprint, row.ruleset_version,
                row.derived_at, deepcopy(row.metadata_json))
               for row in db.query(AudienceSignal).order_by(AudienceSignal.id)]
    pairs = {(row.signal_id, row.evidence_id) for row in db.query(AudienceSignalEvidence)}
    return signals, pairs


def test_ordinary_retry_exhaustion_keeps_one_operation_and_terminal_state(db_session_factory, monkeypatch):
    launched, observation_id = launch(db_session_factory)
    run, mission, execution, authority = state(db_session_factory, launched)
    metadata, payload, run_key = deepcopy(run.metadata_json), mission.input_data, run.idempotency_key
    monkeypatch.setattr(AudienceRepository, "research_run", lambda self, run_id: (_ for _ in ()).throw(RuntimeError("network failure")))
    outcome = attempt(db_session_factory, launched, execution, authority, AudienceSignalExtractionWorkflow(db_session_factory))
    db = db_session_factory()
    try:
        current = db.get(Execution, execution.id); current.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
        assert outcome.lifecycle_status == "QUEUED" and current.status == "QUEUED"
        assert db.get(MissionRecord, mission.id).status == "RETRY_WAIT"
        assert current.lease_owner is None and current.lease_expires_at is None
    finally: db.close()
    for expected_retry_count in (1, 2):
        db = db_session_factory()
        try:
            claimed = ExecutionRepository(db).claim_due_retry(execution.id)
            assert claimed is not None and claimed.status == "RETRYING"
            claimed_id, claimed_authority, retry_count = claimed.id, claimed.retry_authority, claimed.retry_count
            assert claimed.id == execution.id and claimed.mission_id == mission.id
            assert claimed_authority.lease_generation == authority.lease_generation + expected_retry_count
            assert claimed.lease_owner and claimed.lease_expires_at is not None
        finally: db.close()
        outcome = attempt(db_session_factory, launched, type("ExecutionInfo", (), {"id": claimed_id})(), claimed_authority,
                          AudienceSignalExtractionWorkflow(db_session_factory), retry_count)
        db = db_session_factory()
        try:
            current = db.get(Execution, execution.id)
            if expected_retry_count == 1:
                assert outcome.lifecycle_status == "QUEUED" and current.status == "QUEUED"
                current.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
            else:
                assert outcome.lifecycle_status == "FAILED" and current.status == "FAILED"
                assert db.get(MissionRecord, mission.id).status == "FAILED"
                assert db.get(Worker, "Research Agent").status == "ONLINE"
                assert current.next_retry_at is None and current.lease_owner is None and current.lease_expires_at is None
                assert ExecutionRepository(db).claim_due_retry(current.id) is None
                assert db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
        finally: db.close()
    monkeypatch.undo()
    db = db_session_factory()
    try:
        current_run = AudienceRepository(db).research_run(run.id)
        assert current_run.metadata_json == metadata and current_run.idempotency_key == run_key
        assert db.get(MissionRecord, mission.id).input_data == payload
    finally: db.close()
    repeated = AudienceSignalExtractionMissionLaunchService(db_session_factory).launch(observation_id)
    assert repeated.audience_research_run_id == run.id and repeated.mission_id == mission.id
    db = db_session_factory()
    try:
        AudienceFoundationService(db).record_evidence(observation_id=observation_id, source_reference="changed-input", normalized_representation={"event": "unknown"}); db.commit()
    finally: db.close()
    changed = AudienceSignalExtractionMissionLaunchService(db_session_factory).launch(observation_id)
    assert changed.audience_research_run_id != run.id and changed.mission_id != mission.id


def test_phase3r_recovery_replays_committed_signals_and_fences_stale_e1(db_session_factory):
    launched, observation_id = launch(db_session_factory)
    run, mission, e1, e1_authority = state(db_session_factory, launched)
    workflow = AudienceSignalExtractionWorkflow(db_session_factory)
    with activate_execution_runtime_context(ExecutionRuntimeContext(e1_authority, mission.id)):
        first = workflow.execute({"audience_research_run_id": run.id})
    assert first.success and first.data["signal_ids"]
    db = db_session_factory()
    try:
        before_signals, before_pairs = snapshot(db)
        AudienceFoundationService(db).record_evidence(observation_id=observation_id, source_reference="late-evidence", normalized_representation={"event": "unknown"})
        db.get(Execution, e1.id).lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally: db.close()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(e1.id)
    assert recovered is not None
    db = db_session_factory()
    try:
        stale_signals, stale_pairs = snapshot(db)
        with activate_execution_runtime_context(ExecutionRuntimeContext(e1_authority, mission.id)):
            with pytest.raises(ExecutionLeaseLostError):
                workflow.execute({"audience_research_run_id": run.id})
        assert snapshot(db) == (stale_signals, stale_pairs) == (before_signals, before_pairs)
        e2 = db.get(Execution, recovered.replacement_execution_id)
        assert db.get(Execution, e1.id).status == "ABANDONED" and e2.mission_id == mission.id
        assert e2.input_data == e1.input_data
        assert e2.lease_generation == e1_authority.lease_generation + 1 and e2.lease_owner != e1_authority.lease_owner
    finally: db.close()
    outcome = attempt(db_session_factory, launched, type("ExecutionInfo", (), {"id": recovered.replacement_execution_id})(),
                      recovered.authority, AudienceSignalExtractionWorkflow(db_session_factory))
    db = db_session_factory()
    try:
        e2 = db.get(Execution, recovered.replacement_execution_id)
        assert outcome.lifecycle_status == "COMPLETED" and outcome.result.data == first.data
        assert e2.status == db.get(MissionRecord, mission.id).status == "COMPLETED"
        assert db.get(Worker, "Research Agent").status == "ONLINE"
        assert snapshot(db) == (before_signals, before_pairs)
        assert AudienceRepository(db).research_run(run.id).metadata_json == run.metadata_json
    finally: db.close()
    changed = AudienceSignalExtractionMissionLaunchService(db_session_factory).launch(observation_id)
    assert changed.audience_research_run_id != run.id and changed.mission_id != mission.id


def test_phase3r_zero_signal_recovery_completes(db_session_factory):
    launched, _ = launch(db_session_factory, event="unknown", evidence_event="unknown")
    run, mission, e1, authority = state(db_session_factory, launched)
    db = db_session_factory()
    try:
        db.get(Execution, e1.id).lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1); db.commit()
    finally: db.close()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(e1.id)
    outcome = attempt(db_session_factory, launched, type("ExecutionInfo", (), {"id": recovered.replacement_execution_id})(),
                      recovered.authority, AudienceSignalExtractionWorkflow(db_session_factory))
    db = db_session_factory()
    try:
        assert outcome.lifecycle_status == "COMPLETED" and outcome.result.data["candidate_count"] == 0
        assert outcome.result.data["signal_ids"] == [] and db.query(AudienceSignal).count() == 0
    finally: db.close()


def test_committed_e1_signals_survive_later_recovered_e2_failure(db_session_factory, monkeypatch):
    launched, _ = launch(db_session_factory)
    run, mission, e1, e1_authority = state(db_session_factory, launched)
    workflow = AudienceSignalExtractionWorkflow(db_session_factory)
    with activate_execution_runtime_context(ExecutionRuntimeContext(e1_authority, mission.id)):
        assert workflow.execute({"audience_research_run_id": run.id}).success
    db = db_session_factory()
    try:
        before = snapshot(db)
        db.get(Execution, e1.id).lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally: db.close()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(e1.id)
    monkeypatch.setattr(AudienceRepository, "research_run", lambda self, run_id: (_ for _ in ()).throw(RuntimeError("network failure")))
    outcome = attempt(db_session_factory, launched, type("ExecutionInfo", (), {"id": recovered.replacement_execution_id})(),
                      recovered.authority, AudienceSignalExtractionWorkflow(db_session_factory), retry_count=2)
    monkeypatch.undo()
    db = db_session_factory()
    try:
        assert outcome.lifecycle_status == "FAILED"
        assert db.get(MissionRecord, mission.id).status == "FAILED"
        assert snapshot(db) == before
        assert AudienceRepository(db).research_run(run.id).metadata_json == run.metadata_json
    finally: db.close()
