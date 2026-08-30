"""Focused durable NOT_FOUND follow-up publish handoff proofs."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.owned_lifecycle_participants import participant_for_workflow
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5e1_distribution_reconciliation import distribution_run


def setup_reconciliation(db):
    run = distribution_run(db, status="RECONCILING")
    missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
    mission = missions.create("reconcile-source", "Reconcile", "reconcile", "distribution_reconcile", current_worker_name="Content Worker")
    missions.update_status(mission.id, "RUNNING", current_worker_name="Content Worker")
    workers.create("Content Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)
    assert workers.claim("Content Worker", mission.id)
    execution = executions.create("distribution_reconcile", "RUNNING", mission.id, mission.name, "Content Worker", input_data='{"distribution_run_id": "%s"}' % run.id)
    authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
    assert executions.acquire_lease(authority, 600)
    return run, mission, execution, authority


def not_found(run):
    return {"success": True, "workflow": "distribution_reconcile", "data": {"distribution_run_id": run.id, "reconciliation_state": "NOT_FOUND"}, "errors": []}


def handoff(db, run, mission, authority):
    return OwnedExecutionLifecycleCoordinator(db).complete(
        authority, mission_id=mission.id, mission_name=mission.name, worker_name="Content Worker",
        duration=0, result_data="{}", result_payload=not_found(run),
        participant=participant_for_workflow("distribution_reconcile"),
    )


def test_not_found_creates_one_leased_followup_publish_operation(db_session):
    run, mission, execution, authority = setup_reconciliation(db_session)
    result = handoff(db_session, run, mission, authority)
    db_session.expire_all()
    current = db_session.get(type(run), run.id)
    successor = db_session.query(MissionRecord).filter(MissionRecord.id != mission.id).one()
    successor_execution = db_session.query(Execution).filter_by(mission_id=successor.id).one()
    worker = db_session.get(Worker, "Content Worker")
    assert result.status == "COMPLETED" and (current.status, current.publish_generation, current.reconciliation_generation) == ("CREATED", 1, 0)
    assert db_session.get(Execution, execution.id).status == "COMPLETED" and db_session.get(MissionRecord, mission.id).status == "COMPLETED"
    assert successor.idempotency_key == f"distribution-publish:{run.id}:1" and successor.input_data == '{"distribution_run_id": "%s"}' % run.id
    assert (successor.status, successor_execution.status, worker.status, worker.current_mission_id) == ("RUNNING", "RUNNING", "BUSY", successor.id)
    expiry = successor_execution.lease_expires_at.replace(tzinfo=timezone.utc) if successor_execution.lease_expires_at.tzinfo is None else successor_execution.lease_expires_at
    assert successor_execution.lease_owner and successor_execution.lease_generation == 1 and expiry > datetime.now(timezone.utc)


def test_stale_or_duplicate_handoff_cannot_advance_generation(db_session):
    run, mission, execution, authority = setup_reconciliation(db_session)
    execution.status = "ABANDONED"; execution.lease_expires_at = None; db_session.commit()
    with pytest.raises(ExecutionLeaseLostError): handoff(db_session, run, mission, authority)
    db_session.expire_all()
    assert db_session.get(type(run), run.id).publish_generation == 0
    assert db_session.query(MissionRecord).count() == 1 and db_session.query(Execution).count() == 1


def test_committed_not_found_handoff_is_idempotent_on_restart(db_session):
    run, mission, _, authority = setup_reconciliation(db_session)
    handoff(db_session, run, mission, authority)
    # A restart can replay the completed logical handoff, but the terminal
    # predecessor no longer owns an active lease and cannot allocate generation 2.
    with pytest.raises(ExecutionLeaseLostError):
        handoff(db_session, run, mission, authority)
    db_session.expire_all()
    successors = db_session.query(MissionRecord).filter(MissionRecord.id != mission.id).all()
    assert db_session.get(type(run), run.id).publish_generation == 1
    assert len(successors) == 1 and successors[0].idempotency_key == f"distribution-publish:{run.id}:1"
    assert db_session.query(Execution).filter_by(mission_id=successors[0].id).count() == 1
    assert db_session.query(MissionRecord).filter(MissionRecord.idempotency_key.like(f"distribution-publish:{run.id}:2")).count() == 0


def test_fault_after_generation_or_mission_creation_rolls_back(db_session, monkeypatch):
    run, mission, _, authority = setup_reconciliation(db_session)
    monkeypatch.setattr(MissionRepository, "create", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("after generation")))
    with pytest.raises(RuntimeError, match="after generation"): handoff(db_session, run, mission, authority)
    db_session.expire_all()
    assert (db_session.get(type(run), run.id).status, db_session.get(type(run), run.id).publish_generation) == ("RECONCILING", 0)
    assert db_session.query(MissionRecord).count() == 1 and db_session.query(Execution).count() == 1


def test_committed_successor_is_recoverable_before_dispatch(db_session, db_session_factory):
    run, mission, _, authority = setup_reconciliation(db_session)
    successor = handoff(db_session, run, mission, authority).successor
    db_session.execute(__import__("sqlalchemy").text("UPDATE executions SET lease_expires_at = :expired WHERE id = :id"), {"expired": datetime.now(timezone.utc) - timedelta(minutes=1), "id": successor.execution_id})
    db_session.commit()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(successor.execution_id)
    assert recovered is not None and recovered.mission_id == successor.mission_id and recovered.authority.lease_generation == 2
