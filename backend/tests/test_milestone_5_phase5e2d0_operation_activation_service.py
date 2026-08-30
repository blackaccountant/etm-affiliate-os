"""Direct proofs for generic durable operation activation."""

import pytest

from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.worker_repository import WorkerRepository
from app.services.durable_operation_activation_service import (
    DurableOperationActivationService,
    OperationActivationState,
    SuccessorOperationSpec,
)
from app.workforce.status import WorkerStatus


def spec(key="operation-key"):
    return SuccessorOperationSpec("Operation", "proof", "test_workflow", "cap", key, {"distribution_run_id": "run"})


def worker(db, name, capabilities):
    return WorkerRepository(db).create(name, "Test", capabilities, WorkerStatus.ONLINE)


def test_activation_claims_eligible_worker_and_returns_persisted_authority(db_session):
    worker(db_session, "Eligible", ["cap"])
    result = DurableOperationActivationService(db_session).activate(spec())
    execution = db_session.get(Execution, result.execution_id)
    mission = db_session.get(MissionRecord, result.mission_id)
    assert mission.status == execution.status == "RUNNING" and mission.input_data == '{"distribution_run_id": "run"}'
    assert (execution.lease_owner, execution.lease_generation) == (result.authority.lease_owner, result.authority.lease_generation)
    assert execution.lease_expires_at and db_session.get(Worker, "Eligible").current_mission_id == mission.id


def test_preferred_and_capability_fallback_are_db_claimed(db_session):
    worker(db_session, "Wrong", ["other"]); worker(db_session, "Right", ["cap"])
    result = DurableOperationActivationService(db_session).activate(spec(), "Wrong")
    assert result.worker_name == "Right" and db_session.get(Worker, "Wrong").status == "ONLINE"


def test_no_worker_leaves_no_durable_operation_after_caller_rollback(db_session):
    with pytest.raises(RuntimeError, match="no eligible worker"):
        DurableOperationActivationService(db_session).activate(spec())
    db_session.rollback()
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


def test_existing_actionable_operation_preserves_authority_and_worker_ownership(db_session):
    worker(db_session, "Busy", ["cap"])
    worker(db_session, "Available", ["cap"])
    operation_spec = spec("actionable-operation")
    service = DurableOperationActivationService(db_session)
    created = service.activate(operation_spec, "Busy")
    db_session.commit()
    execution = db_session.get(Execution, created.execution_id)
    before = {
        "mission_id": created.mission_id,
        "execution_id": execution.id,
        "lease_owner": execution.lease_owner,
        "lease_generation": execution.lease_generation,
        "mission_count": db_session.query(MissionRecord).count(),
        "execution_count": db_session.query(Execution).count(),
    }

    existing = service.activate(operation_spec)
    current_worker = db_session.get(Worker, "Busy")

    assert existing.state is OperationActivationState.EXISTING_ACTIONABLE
    assert (existing.mission_id, existing.execution_id) == (before["mission_id"], before["execution_id"])
    assert existing.authority == created.authority
    assert db_session.query(MissionRecord).count() == before["mission_count"]
    assert db_session.query(Execution).count() == before["execution_count"]
    assert (execution.lease_owner, execution.lease_generation) == (before["lease_owner"], before["lease_generation"])
    assert (current_worker.status, current_worker.current_mission_id) == ("BUSY", before["mission_id"])
    assert db_session.get(Worker, "Available").status == "ONLINE"


@pytest.mark.parametrize("terminal_status", ["COMPLETED", "FAILED"])
def test_existing_terminal_operation_is_not_reopened_or_claimed(db_session, terminal_status):
    worker(db_session, "TerminalWorker", ["cap"])
    worker(db_session, "Available", ["cap"])
    operation_spec = spec(f"terminal-operation-{terminal_status.lower()}")
    service = DurableOperationActivationService(db_session)
    created = service.activate(operation_spec, "TerminalWorker")
    db_session.commit()
    mission = db_session.get(MissionRecord, created.mission_id)
    execution = db_session.get(Execution, created.execution_id)
    mission.status = terminal_status
    mission.current_worker_name = None
    execution.status = terminal_status
    execution.lease_expires_at = None
    assert WorkerRepository(db_session).release("TerminalWorker", mission.id, success=terminal_status == "COMPLETED", commit=False)
    db_session.commit()
    before_missions = db_session.query(MissionRecord).count()
    before_executions = db_session.query(Execution).count()

    existing = service.activate(operation_spec)

    assert existing.state is OperationActivationState.EXISTING_TERMINAL
    assert existing.mission_id == mission.id
    assert db_session.get(MissionRecord, mission.id).status == terminal_status
    assert db_session.query(MissionRecord).count() == before_missions
    assert db_session.query(Execution).count() == before_executions
    assert db_session.get(Worker, "TerminalWorker").status == "ONLINE"
    assert db_session.get(Worker, "Available").status == "ONLINE"
