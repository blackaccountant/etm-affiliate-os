"""B.3B post-commit, pre-lifecycle restart safety for audience extraction."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import socket

import pytest

from app.models.audience import AudienceSignal, AudienceSignalEvidence
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.repositories.audience_repository import AudienceRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_extraction_mission_launch_service import AudienceSignalExtractionMissionLaunchService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.workflows.audience.audience_signal_extraction_workflow import AudienceSignalExtractionWorkflow
from app.workforce.status import WorkerStatus


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("B.3B must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def launch_operation(factory, *, event="pricing", evidence_event="comparison"):
    db = factory()
    try:
        foundation = AudienceFoundationService(db)
        observation = foundation.ingest_observation(
            research_run_id=None, subject_id=None, source_namespace="restart-test", source_type="MANUAL",
            external_observation_id=None, source_reference="restart-observation",
            observed_at=datetime.now(timezone.utc), normalized_fact={"event": event},
        )
        foundation.record_evidence(
            observation_id=observation.id, source_reference="restart-evidence",
            normalized_representation={"event": evidence_event},
        )
        WorkerRepository(db).create("Research Agent", "AI Agent", ["audience_signal_extraction"], WorkerStatus.ONLINE)
        db.commit()
        launched = AudienceSignalExtractionMissionLaunchService(factory).launch(observation.id)
        return launched, observation.id
    finally:
        db.close()


def operation_state(factory, launched):
    db = factory()
    try:
        run = AudienceRepository(db).research_run(launched.audience_research_run_id)
        mission = db.get(MissionRecord, launched.mission_id)
        execution = db.query(Execution).filter_by(mission_id=mission.id).one()
        authority = ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)
        return (
            deepcopy(run.metadata_json), run.id, run.idempotency_key, mission.id,
            mission.idempotency_key, mission.input_data, execution.id, authority,
        )
    finally:
        db.close()


def execute_business_work(factory, launched, authority):
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        return AudienceSignalExtractionWorkflow(session_factory=factory).execute(
            {"audience_research_run_id": launched.audience_research_run_id}
        )


def signal_snapshot(db):
    rows = db.query(AudienceSignal).order_by(AudienceSignal.id).all()
    values = [
        (
            row.id, row.subject_id, row.signal_type, row.topic_slug, row.topic_label,
            row.intent_stage, row.strength, row.confidence, row.evidence_set_fingerprint,
            row.extraction_key, row.ruleset_version, row.model_version, row.observed_at,
            row.derived_at, row.expires_at, row.supersedes_signal_id, row.rationale,
            deepcopy(row.metadata_json),
        )
        for row in rows
    ]
    pairs = {
        (row.signal_id, row.evidence_id)
        for row in db.query(AudienceSignalEvidence).all()
    }
    return values, pairs


def complete_lifecycle(factory, launched, authority, result):
    db = factory()
    try:
        mission = db.get(MissionRecord, launched.mission_id)
        OwnedExecutionLifecycleCoordinator(db).complete(
            authority, mission_id=mission.id, mission_name=mission.name,
            worker_name="Research Agent", duration=0.0,
            result_data=json.dumps(result.data), result_payload=result.data,
        )
    finally:
        db.close()


def test_post_commit_restart_reuses_snapshot_signals_and_ignores_new_evidence(db_session_factory):
    launched, observation_id = launch_operation(db_session_factory)
    metadata, run_id, run_key, mission_id, mission_key, payload, execution_id, authority = operation_state(db_session_factory, launched)
    first = execute_business_work(db_session_factory, launched, authority)
    assert first.success and first.data["candidate_count"] > 0 and first.data["signal_ids"]

    db = db_session_factory()
    try:
        first_rows, first_pairs = signal_snapshot(db)
        assert db.get(Execution, execution_id).status == "RUNNING"
        assert db.get(MissionRecord, mission_id).status == "RUNNING"
        assert db.query(AudienceSignal).count() == len(first_rows)
        AudienceFoundationService(db).record_evidence(
            observation_id=observation_id, source_reference="new-after-crash",
            normalized_representation={"event": "unknown"},
        )
        db.commit()
    finally:
        db.close()

    replay = execute_business_work(db_session_factory, launched, authority)
    assert replay.success and replay.data == first.data
    db = db_session_factory()
    try:
        replay_rows, replay_pairs = signal_snapshot(db)
        run = AudienceRepository(db).research_run(run_id)
        mission = db.get(MissionRecord, mission_id)
        assert replay_rows == first_rows and replay_pairs == first_pairs
        assert run.id == run_id and run.idempotency_key == run_key and run.metadata_json == metadata
        assert mission.id == mission_id and mission.idempotency_key == mission_key and mission.input_data == payload
        assert db.query(AudienceSignal).count() == len(first_rows)
        assert db.query(AudienceSignalEvidence).count() == len(first_pairs)
    finally:
        db.close()

    complete_lifecycle(db_session_factory, launched, authority, replay)
    changed = AudienceSignalExtractionMissionLaunchService(db_session_factory).launch(observation_id)
    assert changed.audience_research_run_id != run_id and changed.mission_id != mission_id


def test_zero_signal_post_commit_restart_is_stable(db_session_factory):
    launched, _ = launch_operation(db_session_factory, event="unknown", evidence_event="unknown")
    _, _, _, mission_id, _, _, execution_id, authority = operation_state(db_session_factory, launched)
    first = execute_business_work(db_session_factory, launched, authority)
    assert first.success and first.data["candidate_count"] == 0 and first.data["signal_ids"] == []
    db = db_session_factory()
    try:
        assert db.get(Execution, execution_id).status == db.get(MissionRecord, mission_id).status == "RUNNING"
        assert db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
    finally:
        db.close()
    replay = execute_business_work(db_session_factory, launched, authority)
    db = db_session_factory()
    try:
        assert replay.success and replay.data == first.data
        assert db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
    finally:
        db.close()


def test_pre_commit_technical_failure_remains_atomic(db_session_factory, monkeypatch):
    launched, _ = launch_operation(db_session_factory)
    _, _, _, _, _, _, execution_id, authority = operation_state(db_session_factory, launched)
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

    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        with pytest.raises(RuntimeError, match="network failure"):
            AudienceSignalExtractionWorkflow(session_factory=transaction_factory).execute(
                {"audience_research_run_id": launched.audience_research_run_id}
            )
    db = db_session_factory()
    try:
        assert calls and db.query(AudienceSignal).count() == db.query(AudienceSignalEvidence).count() == 0
    finally:
        db.close()


def test_terminal_duplicate_launch_reuses_completed_operation(db_session_factory):
    launched, observation_id = launch_operation(db_session_factory)
    _, run_id, _, mission_id, _, _, execution_id, authority = operation_state(db_session_factory, launched)
    result = execute_business_work(db_session_factory, launched, authority)
    assert result.success
    complete_lifecycle(db_session_factory, launched, authority, result)
    repeated = AudienceSignalExtractionMissionLaunchService(db_session_factory).launch(observation_id)
    db = db_session_factory()
    try:
        assert repeated.audience_research_run_id == run_id and repeated.mission_id == mission_id
        assert db.get(MissionRecord, mission_id).status == "COMPLETED"
        assert db.query(MissionRecord).count() == 1
        assert db.query(Execution).count() == 1 and db.get(Execution, execution_id).status == "COMPLETED"
    finally:
        db.close()
