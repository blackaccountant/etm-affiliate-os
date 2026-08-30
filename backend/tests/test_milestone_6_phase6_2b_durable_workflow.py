"""SQLite functional proofs for the M6.2B.2 durable extraction operation."""

from datetime import datetime, timezone
from copy import deepcopy
import socket

import pytest

from app.audience.signal_extraction_mission_contracts import AudienceSignalExtractionSnapshot
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.audience import AudienceSignal, AudienceSignalEvidence
from app.repositories.audience_repository import AudienceRepository
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_extraction_mission_launch_service import AudienceSignalExtractionMissionLaunchService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.workflows.audience.audience_signal_extraction_workflow import AudienceSignalExtractionWorkflow
from app.workforce.status import WorkerStatus


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("B.2 durable extraction must not access the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def seed_observation(db, *, event="pricing", evidence_event=None):
    foundation = AudienceFoundationService(db)
    observation = foundation.ingest_observation(
        research_run_id=None, subject_id=None, source_namespace="test", source_type="MANUAL",
        external_observation_id=None, source_reference="test-observation",
        observed_at=datetime.now(timezone.utc), normalized_fact={"event": event},
    )
    foundation.record_evidence(
        observation_id=observation.id, source_reference="test-evidence",
        normalized_representation={"event": evidence_event or event},
    )
    db.commit()
    return observation


def launcher(factory):
    return AudienceSignalExtractionMissionLaunchService(factory)


def add_research_worker(db, name="Research Agent"):
    return WorkerRepository(db).create(
        name, "AI Agent", ["audience_signal_extraction"], WorkerStatus.ONLINE,
    )


def authority_for(db, mission_id):
    execution = db.query(Execution).filter_by(mission_id=mission_id).one()
    return ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)


def test_launch_creates_immutable_snapshot_and_reuses_identical_operation(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    first = launcher(db_session_factory).launch(observation.id)
    second = launcher(db_session_factory).launch(observation.id)
    run = AudienceRepository(db_session).research_run(first.audience_research_run_id)
    snapshot = AudienceSignalExtractionSnapshot.from_metadata(run.metadata_json)
    mission = db_session.get(MissionRecord, first.mission_id)
    assert first.audience_research_run_id == second.audience_research_run_id
    assert first.mission_id == second.mission_id and snapshot.observation_id == observation.id
    assert mission.idempotency_key == first.idempotency_key
    assert mission.input_data == '{"audience_research_run_id": "' + run.id + '"}'


def test_changed_ruleset_and_evidence_create_new_operation_identity(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); add_research_worker(db_session, "Research Agent 2"); add_research_worker(db_session, "Research Agent 3"); db_session.commit()
    first = launcher(db_session_factory).launch(observation.id)
    db_session.expire_all()
    AudienceFoundationService(db_session).record_evidence(
        observation_id=observation.id, source_reference="additional-evidence", normalized_representation={"event": "compare"},
    ); db_session.commit()
    changed = launcher(db_session_factory).launch(observation.id)
    assert changed.audience_research_run_id != first.audience_research_run_id
    changed_ruleset = launcher(db_session_factory).launch(observation.id, ruleset_version="audience-signal-extraction-v2")
    assert changed_ruleset.audience_research_run_id != changed.audience_research_run_id


def test_terminal_mission_is_not_reopened(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    first = launcher(db_session_factory).launch(observation.id)
    mission = db_session.get(MissionRecord, first.mission_id); execution = db_session.query(Execution).filter_by(mission_id=mission.id).one()
    mission.status = "COMPLETED"; execution.status = "COMPLETED"; execution.lease_expires_at = None; db_session.commit()
    repeated = launcher(db_session_factory).launch(observation.id)
    assert repeated.mission_id == mission.id and db_session.get(MissionRecord, mission.id).status == "COMPLETED"


def test_workflow_replays_exact_snapshot_and_persists_idempotently(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    authority = authority_for(db_session, launched.mission_id)
    payload = {"audience_research_run_id": launched.audience_research_run_id}
    workflow = AudienceSignalExtractionWorkflow(session_factory=db_session_factory)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        first = workflow.execute(payload)
    db_session.expire_all()
    execution = db_session.get(Execution, authority.execution_id)
    execution.status = "RUNNING"; execution.lease_expires_at = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1); db_session.commit()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        second = workflow.execute(payload)
    assert first.success and second.success and first.data["signal_ids"] == second.data["signal_ids"]
    assert db_session.query(AudienceSignal).count() == 1


def test_workflow_rejects_missing_or_drifted_snapshot_input(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    authority = authority_for(db_session, launched.mission_id)
    evidence = AudienceRepository(db_session).evidence_for_observation(observation.id)[0]
    evidence.evidence_fingerprint = "f" * 64; db_session.commit()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        result = AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute({"audience_research_run_id": launched.audience_research_run_id})
    assert result.success is False and "fingerprint mismatch" in result.errors[0]


def test_missing_snapshotted_evidence_is_a_permanent_replay_failure(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    run = AudienceRepository(db_session).research_run(launched.audience_research_run_id)
    metadata_before = deepcopy(run.metadata_json)
    evidence = AudienceRepository(db_session).evidence_for_observation(observation.id)[0]
    db_session.delete(evidence); db_session.commit()
    authority = authority_for(db_session, launched.mission_id)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        result = AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute({"audience_research_run_id": run.id})
    db_session.expire_all()
    assert result.success is False and "snapshotted audience input is missing" in result.errors[0]
    assert db_session.query(AudienceSignal).count() == db_session.query(AudienceSignalEvidence).count() == 0
    assert AudienceRepository(db_session).research_run(run.id).metadata_json == metadata_before


def test_malformed_snapshot_metadata_is_a_typed_workflow_validation_failure(db_session, db_session_factory, monkeypatch):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    run = AudienceRepository(db_session).research_run(launched.audience_research_run_id)
    metadata_before = {"operation_kind": "audience_signal_extract"}; run.metadata_json = metadata_before; db_session.commit()
    called = []
    monkeypatch.setattr("app.workflows.audience.audience_signal_extraction_workflow.extract", lambda *args, **kwargs: called.append(True))
    authority = authority_for(db_session, launched.mission_id)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        result = AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute({"audience_research_run_id": run.id})
    assert result.success is False and result.errors[0].startswith("validation error:")
    assert called == [] and db_session.query(AudienceSignal).count() == db_session.query(AudienceSignalEvidence).count() == 0
    assert AudienceRepository(db_session).research_run(run.id).metadata_json == metadata_before


def test_wrong_operation_kind_is_a_typed_workflow_validation_failure(db_session, db_session_factory, monkeypatch):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    run = AudienceRepository(db_session).research_run(launched.audience_research_run_id)
    invalid_metadata = deepcopy(run.metadata_json); invalid_metadata["operation_kind"] = "other_operation"; run.metadata_json = invalid_metadata; db_session.commit()
    called = []
    monkeypatch.setattr("app.workflows.audience.audience_signal_extraction_workflow.extract", lambda *args, **kwargs: called.append(True))
    authority = authority_for(db_session, launched.mission_id)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        result = AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute({"audience_research_run_id": run.id})
    assert result.success is False and result.errors[0].startswith("validation error:")
    assert called == [] and db_session.query(AudienceSignal).count() == db_session.query(AudienceSignalEvidence).count() == 0
    assert AudienceRepository(db_session).research_run(run.id).metadata_json == invalid_metadata


def test_workflow_owns_distinct_and_closed_sessions_on_success_and_failure(db_session, db_session_factory):
    observation = seed_observation(db_session); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    authority = authority_for(db_session, launched.mission_id)
    sessions = []

    class TrackedSession:
        def __init__(self): self.inner, self.closed = db_session_factory(), False
        def close(self): self.closed = True; self.inner.close()
        def __getattr__(self, name): return getattr(self.inner, name)

    def factory():
        session = TrackedSession(); sessions.append(session); return session

    workflow = AudienceSignalExtractionWorkflow(session_factory=factory)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        success = workflow.execute({"audience_research_run_id": launched.audience_research_run_id})
    run = AudienceRepository(db_session).research_run(launched.audience_research_run_id)
    run.metadata_json = {"operation_kind": "audience_signal_extract"}; db_session.commit()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        failure = workflow.execute({"audience_research_run_id": launched.audience_research_run_id})
    assert success.success and failure.success is False
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert all(session.closed for session in sessions)


def test_zero_signal_is_success(db_session, db_session_factory):
    observation = seed_observation(db_session, event="unknown"); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    authority = authority_for(db_session, launched.mission_id)
    payload = {"audience_research_run_id": launched.audience_research_run_id}
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        zero = AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute(payload)
    assert zero.success and zero.data["candidate_count"] == 0
    assert db_session.query(AudienceSignal).count() == 0


def test_stale_authority_cannot_write_signal(db_session, db_session_factory):
    observation = seed_observation(db_session, event="pricing"); add_research_worker(db_session); db_session.commit()
    launched = launcher(db_session_factory).launch(observation.id)
    authority = authority_for(db_session, launched.mission_id)
    db_session.get(Execution, authority.execution_id).lease_generation += 1; db_session.commit()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, launched.mission_id)):
        with pytest.raises(ExecutionLeaseLostError):
            AudienceSignalExtractionWorkflow(session_factory=db_session_factory).execute({"audience_research_run_id": launched.audience_research_run_id})
    assert db_session.query(AudienceSignal).count() == 0


def test_registry_and_capability_are_registered_once():
    from app.registry.default_workflows import create_workflow_registry
    from app.workforce.default_workers import create_default_workers

    assert list(create_workflow_registry().all()).count("audience_signal_extract") == 1
    worker = next(item for item in create_default_workers() if item.name == "Research Agent")
    assert worker.capabilities.count("audience_signal_extraction") == 1
