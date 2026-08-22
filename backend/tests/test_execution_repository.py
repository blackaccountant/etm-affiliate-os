from datetime import datetime, timezone, timedelta

from app.models.execution import Execution
from app.repositories.execution_repository import (
    ExecutionRepository,
)



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


    execution = Execution(

        workflow_name="affiliate_discovery",

        status="FAILED",

        retry_count=0,

        max_retries=3,

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



def test_claim_retry_changes_status(
    db_session,
):

    repository = ExecutionRepository(
        db_session
    )


    execution = Execution(

        workflow_name="affiliate_discovery",

        status="QUEUED",

        retry_count=1,

        max_retries=3,

    )


    db_session.add(
        execution
    )

    db_session.commit()

    db_session.refresh(
        execution
    )


    claimed = repository.claim_retry(
        execution
    )


    assert (
        claimed.status
        == "RETRYING"
    )