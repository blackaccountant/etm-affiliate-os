from datetime import datetime, timezone, timedelta

from app.models.execution import Execution
from app.repositories.execution_repository import (
    ExecutionRepository,
)
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.workforce.status import WorkerStatus



def test_execution_model_exists():

    assert Execution.__tablename__ == "executions"



def test_execution_model_has_retry_fields():

    fields = (
        Execution.__table__
        .columns
        .keys()
    )


    assert "retry_count" in fields

    assert "max_retries" in fields

    assert "next_retry_at" in fields

    assert "failure_type" in fields

    assert "error" in fields



def test_schedule_retry_and_get_retryable(
    db_session,
):

    repository = ExecutionRepository(
        db_session
    )
    missions = MissionRepository(db_session)
    workers = WorkerRepository(db_session)
    mission = missions.create(
        "claim-due-retry", "Claim due retry", "test", "affiliate_discovery",
        current_worker_name="Retry Worker",
    )
    missions.update_status(mission.id, "RETRY_WAIT", current_worker_name="Retry Worker")
    workers.create("Retry Worker", "Test", status=WorkerStatus.ONLINE)
    assert workers.claim("Retry Worker", mission.id)


    execution = Execution(

        workflow_name="affiliate_discovery",

        status="FAILED",

        retry_count=0,

        max_retries=3,

        mission_id=mission.id,

        worker_name="Retry Worker",

        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),

    )


    db_session.add(
        execution
    )

    db_session.commit()

    db_session.refresh(
        execution
    )


    retry_time = (
        datetime.now(timezone.utc)
        -
        timedelta(seconds=1)
    )


    updated = repository.schedule_retry(

        execution=execution,

        retry_count=1,

        max_retries=3,

        next_retry_at=retry_time,

        failure_type="NETWORK",

        error="Connection timeout",

    )


    assert (
        updated.status
        == "QUEUED"
    )


    assert (
        updated.retry_count
        == 1
    )


    queue = repository.get_retryable()


    assert len(queue) == 1


    assert (
        queue[0].failure_type
        == "NETWORK"
    )



def test_claim_due_retry_changes_status(
    db_session,
):

    repository = ExecutionRepository(
        db_session
    )
    missions = MissionRepository(db_session)
    workers = WorkerRepository(db_session)
    mission = missions.create(
        "claim-due-retry-positive", "Claim due retry", "test", "affiliate_discovery",
        current_worker_name="Retry Worker",
    )
    missions.update_status(mission.id, "RETRY_WAIT", current_worker_name="Retry Worker")
    workers.create("Retry Worker", "Test", status=WorkerStatus.ONLINE)
    assert workers.claim("Retry Worker", mission.id)


    execution = Execution(

        workflow_name="affiliate_discovery",

        status="QUEUED",

        retry_count=1,

        max_retries=3,

        mission_id=mission.id,

        worker_name="Retry Worker",

        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),

    )


    db_session.add(
        execution
    )

    db_session.commit()

    db_session.refresh(
        execution
    )


    claimed = repository.claim_due_retry(execution.id)


    assert (
        claimed.status
        == "RETRYING"
    )
    expiry = claimed.lease_expires_at.replace(tzinfo=timezone.utc)
    assert claimed.lease_owner and claimed.lease_generation == 1 and expiry > datetime.now(timezone.utc)
    db_session.expire_all()
    assert db_session.get(type(mission), mission.id).status == "RUNNING"
    worker = db_session.get(type(workers.get_by_name("Retry Worker")), "Retry Worker")
    assert worker.status == "BUSY" and worker.current_mission_id == mission.id
