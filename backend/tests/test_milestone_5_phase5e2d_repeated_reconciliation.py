"""Focused durable proofs for explicit reconciliation generations."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.distribution.mission_contracts import distribution_reconciliation_mission_idempotency_key
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.worker_repository import WorkerRepository
from app.services.content_distribution_reconciliation_mission_launch_service import ContentDistributionReconciliationMissionLaunchService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.owned_lifecycle_participants import participant_for_workflow
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5e1_distribution_reconciliation import distribution_run


def _worker(db, name):
    return WorkerRepository(db).create(name, "Test", ["content_distribution"], WorkerStatus.ONLINE)


def _operation(db, mission_id):
    execution = db.query(Execution).filter_by(mission_id=mission_id).one()
    return execution, ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)


def _complete_reconciliation(db, mission_id, state):
    mission = db.get(MissionRecord, mission_id)
    execution, authority = _operation(db, mission_id)
    return OwnedExecutionLifecycleCoordinator(db).complete(
        authority, mission_id=mission.id, mission_name=mission.name,
        worker_name=execution.worker_name, duration=0, result_data="{}",
        result_payload={"success": True, "workflow": "distribution_reconcile", "data": {
            "distribution_run_id": json.loads(execution.input_data)["distribution_run_id"],
            "reconciliation_state": state,
        }},
        participant=participant_for_workflow("distribution_reconcile"),
    )


def test_repeated_generations_are_durable_and_duplicate_safe(db_session, db_session_factory):
    run = distribution_run(db_session)
    _worker(db_session, "Worker A")
    dispatched = []
    launcher = ContentDistributionReconciliationMissionLaunchService(
        session_factory=db_session_factory, dispatch=dispatched.append,
    )

    first = launcher.launch(run.id)
    first_execution, first_authority = _operation(db_session, first.mission_id)
    duplicate = launcher.launch(run.id)
    assert first.mission_id == duplicate.mission_id
    assert db_session.get(type(run), run.id).reconciliation_generation == 0
    assert (first_execution.lease_owner, first_execution.lease_generation) == (first_authority.lease_owner, 1)
    assert db_session.get(Worker, "Worker A").current_mission_id == first.mission_id
    assert len(dispatched) == 1

    _complete_reconciliation(db_session, first.mission_id, "UNKNOWN")
    second = launcher.launch(run.id)
    db_session.expire_all()
    assert db_session.get(type(run), run.id).reconciliation_generation == 1
    assert second.idempotency_key == distribution_reconciliation_mission_idempotency_key(run.id, 1)
    _complete_reconciliation(db_session, second.mission_id, "MANUAL_REQUIRED")
    third = launcher.launch(run.id)

    db_session.expire_all()
    missions = db_session.query(MissionRecord).order_by(MissionRecord.idempotency_key).all()
    assert [mission.idempotency_key for mission in missions] == [
        distribution_reconciliation_mission_idempotency_key(run.id),
        distribution_reconciliation_mission_idempotency_key(run.id, 1),
        distribution_reconciliation_mission_idempotency_key(run.id, 2),
    ]
    assert [mission.status for mission in missions] == ["COMPLETED", "COMPLETED", "RUNNING"]
    assert all(mission.input_data == '{"distribution_run_id": "%s"}' % run.id for mission in missions)
    assert db_session.query(Execution).count() == 3
    assert third.idempotency_key == distribution_reconciliation_mission_idempotency_key(run.id, 2)


def test_terminal_failure_advances_once_and_no_worker_rolls_back_generation(db_session, db_session_factory):
    run = distribution_run(db_session)
    _worker(db_session, "Worker A")
    launcher = ContentDistributionReconciliationMissionLaunchService(session_factory=db_session_factory)
    first = launcher.launch(run.id)
    mission = db_session.get(MissionRecord, first.mission_id)
    execution, authority = _operation(db_session, mission.id)
    OwnedExecutionLifecycleCoordinator(db_session).fail(
        authority, mission_id=mission.id, mission_name=mission.name, worker_name=execution.worker_name,
        duration=0, result_data="{}", result_payload={"success": False}, error="failed",
        failure_type="TEST", retry_count=0,
    )
    db_session.get(type(run), run.id).status = "RECONCILIATION_REQUIRED"
    db_session.commit()
    _worker(db_session, "Worker B")
    second = launcher.launch(run.id)
    assert second.idempotency_key == distribution_reconciliation_mission_idempotency_key(run.id, 1)

    second_execution, second_authority = _operation(db_session, second.mission_id)
    OwnedExecutionLifecycleCoordinator(db_session).fail(
        second_authority, mission_id=second.mission_id, mission_name=second.mission_id,
        worker_name=second_execution.worker_name, duration=0, result_data="{}", result_payload={"success": False},
        error="failed", failure_type="TEST", retry_count=0,
    )
    db_session.get(type(run), run.id).status = "RECONCILIATION_REQUIRED"
    db_session.query(Worker).update({Worker.status: "OFFLINE"})
    db_session.commit()
    with pytest.raises(RuntimeError, match="no eligible worker"):
        launcher.launch(run.id)
    db_session.expire_all()
    assert db_session.get(type(run), run.id).reconciliation_generation == 1
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 2


@pytest.mark.parametrize("status", ["PUBLISHING", "COMPLETED"])
def test_non_reconciliation_states_are_not_stolen(db_session, db_session_factory, status):
    run = distribution_run(db_session, status=status)
    with pytest.raises(RuntimeError, match="reconciliation-required"):
        ContentDistributionReconciliationMissionLaunchService(session_factory=db_session_factory).launch(run.id)
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


def test_committed_generation_recovers_without_creating_another_generation(db_session, db_session_factory):
    run = distribution_run(db_session)
    _worker(db_session, "Worker A")
    launched = ContentDistributionReconciliationMissionLaunchService(session_factory=db_session_factory).launch(run.id)
    execution, _ = _operation(db_session, launched.mission_id)
    execution.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(execution.id)
    db_session.expire_all()
    assert recovered is not None and recovered.mission_id == launched.mission_id
    assert db_session.get(type(run), run.id).reconciliation_generation == 0
    assert db_session.query(MissionRecord).count() == 1
