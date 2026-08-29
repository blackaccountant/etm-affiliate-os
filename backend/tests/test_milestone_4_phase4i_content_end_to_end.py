"""Final isolated integration gate for the Mission-backed content API."""

import inspect
from datetime import datetime, timezone

from fastapi import FastAPI

from app.api.content import router
from app.content_intelligence.generation_contracts import ProviderFailureCategory
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.content_evaluation import ContentEvaluation
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.task_queue.task import Task
from app.executor.executor import TaskExecutor
from app.workforce.status import WorkerStatus

from tests.test_milestone_4_phase4h_content_api import (
    Provider,
    client,
    failure,
    isolation_sentinels,
    manager,
    ready_runs,
    success,
)


def _retry_after_restart(factory, workforce, engine):
    """Run the frozen durable retry path with fresh runtime objects."""
    db = factory()
    try:
        service = ExecutionService(ExecutionRepository(db))
        queued = db.query(Execution).filter_by(status="QUEUED").all()
        assert len(queued) == 1
        queued[0].next_retry_at = datetime.now(timezone.utc)
        db.commit()
        task = Task("content", {})
        task.next_retry_at = None
        tasks = RetryScanner(service, Scheduler()).scan_once(limit=10)
        assert len(tasks) == 1
        executor = TaskExecutor(execution_service=service)
        executor.engine = engine
        executor.workforce = None
        return RetryLifecycleCoordinator(
            db,
            service,
            MissionRepository(db),
            WorkerRepository(db),
            workforce,
            executor,
        ).execute(tasks[0])
    finally:
        db.close()


def _counts(db):
    return {
        "missions": db.query(MissionRecord).count(),
        "executions": db.query(Execution).count(),
        "artifacts": db.query(GeneratedContentArtifact).count(),
        "evaluations": db.query(ContentEvaluation).count(),
    }


def test_generation_api_success_duplicate_readback_and_artifact_retrieval(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    baseline = _counts(db_session)
    provider = Provider([success()])
    api = client(db_session_factory, manager(db_session_factory, provider, Provider([success()])))
    first = api.post(f"/content/generation-runs/{generation.id}/launch")
    second = api.post(f"/content/generation-runs/{generation.id}/launch")
    assert first.status_code == second.status_code == 200
    launch = first.json()
    mission = api.get(f"/content/missions/{launch['mission_id']}").json()
    run = api.get(f"/content/generation-runs/{generation.id}").json()
    artifact = api.get(f"/content/artifacts/{launch['result_data']['artifact_id']}").json()
    assert launch["mission_id"] == second.json()["mission_id"] == mission["id"]
    assert launch["result_data"] == mission["result_data"]
    assert launch["result_data"]["content_generation_run_id"] == run["id"] == generation.id
    assert artifact["generation_run_id"] == generation.id and artifact["body"] == "The program pays 20% commission."
    assert _counts(db_session) == {"missions": 1, "executions": 1, "artifacts": baseline["artifacts"] + 1, "evaluations": baseline["evaluations"] + 1}
    assert provider.calls == 1 and db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value


def test_generation_retry_restart_and_api_readback(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    provider = Provider([failure(), success()])
    initial = manager(db_session_factory, provider, Provider([success()]))
    launched = client(db_session_factory, initial).post(f"/content/generation-runs/{generation.id}/launch")
    assert launched.status_code == 200 and launched.json()["mission_status"] == "RETRY_WAIT"
    db_session.expire_all()
    before = db_session.get(MissionRecord, launched.json()["mission_id"]), db_session.get(ContentGenerationRun, generation.id), db_session.query(Execution).one(), db_session.get(Worker, "Content Writer")
    assert (before[0].status, before[1].status, before[2].status, before[3].status) == ("RETRY_WAIT", "RETRY_WAIT", "QUEUED", WorkerStatus.BUSY.value)
    restarted = manager(db_session_factory, provider, Provider([success()]))
    _retry_after_restart(db_session_factory, restarted.workforce, restarted.executor.engine)
    db_session.expire_all()
    api = client(db_session_factory, restarted)
    mission = api.get(f"/content/missions/{launched.json()['mission_id']}").json()
    run = api.get(f"/content/generation-runs/{generation.id}").json()
    assert mission["status"] == run["status"] == "COMPLETED" and mission["result_data"]["content_generation_run_id"] == generation.id
    assert provider.calls == 2 and _counts(db_session)["missions"] == _counts(db_session)["executions"] == 1
    assert _counts(db_session)["artifacts"] == _counts(db_session)["evaluations"] == 2
    assert db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value


def test_generation_permanent_failure_is_safe_and_terminal(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    provider = Provider([failure(ProviderFailureCategory.AUTHENTICATION)])
    api = client(db_session_factory, manager(db_session_factory, provider, Provider([success()])))
    launch = api.post(f"/content/generation-runs/{generation.id}/launch")
    mission = api.get(f"/content/missions/{launch.json()['mission_id']}").json()
    db_session.expire_all()
    assert launch.status_code == 200 and launch.json()["mission_status"] == mission["status"] == "FAILED"
    assert db_session.get(ContentGenerationRun, generation.id).status == "FAILED"
    assert db_session.query(Execution).one().status == "FAILED" and db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value
    assert "provider" not in mission["result_error"].lower() and "password" not in launch.text.lower()


def test_generation_waiting_worker_has_no_execution_or_provider_call(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    provider = Provider([success()])
    api = client(db_session_factory, manager(db_session_factory, provider, Provider([success()]), workers=False))
    first = api.post(f"/content/generation-runs/{generation.id}/launch")
    second = api.post(f"/content/generation-runs/{generation.id}/launch")
    assert first.status_code == second.status_code == 200 and first.json()["mission_status"] == "WAITING_FOR_WORKER"
    assert first.json()["mission_id"] == second.json()["mission_id"] and provider.calls == 0
    assert db_session.query(Execution).count() == 0 and db_session.get(ContentGenerationRun, generation.id).status == "CREATED"


def test_repurposing_api_success_duplicate_readback_and_artifact_retrieval(db_session, db_session_factory):
    _, repurposing = ready_runs(db_session)
    baseline = _counts(db_session)
    provider = Provider([success()])
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), provider))
    first = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    second = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    assert first.status_code == second.status_code == 200
    launch = first.json()
    mission = api.get(f"/content/missions/{launch['mission_id']}").json()
    run = api.get(f"/content/repurposing-runs/{repurposing.id}").json()
    artifact = api.get(f"/content/artifacts/{launch['result_data']['result_artifact_id']}").json()
    assert launch["mission_id"] == second.json()["mission_id"] == mission["id"] and launch["result_data"] == mission["result_data"]
    assert run["id"] == repurposing.id and artifact["id"] == run["result_artifact_id"]
    assert artifact["generation_run_id"] == run["generation_run_id"] and provider.calls == 1
    assert _counts(db_session) == {"missions": 1, "executions": 1, "artifacts": baseline["artifacts"] + 1, "evaluations": baseline["evaluations"] + 1}
    assert db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value


def test_repurposing_retry_restart_and_api_readback(db_session, db_session_factory):
    _, repurposing = ready_runs(db_session)
    provider = Provider([failure(), success()])
    initial = manager(db_session_factory, Provider([success()]), provider)
    launched = client(db_session_factory, initial).post(f"/content/repurposing-runs/{repurposing.id}/launch")
    assert launched.status_code == 200 and launched.json()["mission_status"] == "RETRY_WAIT"
    db_session.expire_all()
    row = db_session.get(ContentRepurposingRun, repurposing.id)
    linked = db_session.get(ContentGenerationRun, row.generation_run_id)
    assert (row.status, linked.status, db_session.query(Execution).one().status) == ("RUNNING", "RETRY_WAIT", "QUEUED")
    restarted = manager(db_session_factory, Provider([success()]), provider)
    _retry_after_restart(db_session_factory, restarted.workforce, restarted.executor.engine)
    db_session.expire_all()
    api = client(db_session_factory, restarted)
    mission = api.get(f"/content/missions/{launched.json()['mission_id']}").json()
    refreshed = api.get(f"/content/repurposing-runs/{repurposing.id}").json()
    assert mission["status"] == refreshed["status"] == "COMPLETED" and mission["result_data"]["content_repurposing_run_id"] == repurposing.id
    assert db_session.get(ContentGenerationRun, refreshed["generation_run_id"]).status == "COMPLETED" and provider.calls == 2
    assert _counts(db_session)["missions"] == _counts(db_session)["executions"] == 1 and db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value


def test_repurposing_permanent_failure_is_safe_and_terminal(db_session, db_session_factory):
    _, repurposing = ready_runs(db_session)
    provider = Provider([failure(ProviderFailureCategory.AUTHENTICATION)])
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), provider))
    launch = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    mission = api.get(f"/content/missions/{launch.json()['mission_id']}").json()
    db_session.expire_all()
    row = db_session.get(ContentRepurposingRun, repurposing.id)
    assert launch.status_code == 200 and mission["status"] == row.status == "FAILED"
    assert db_session.get(ContentGenerationRun, row.generation_run_id).status == "FAILED"
    assert db_session.query(Execution).one().status == "FAILED" and db_session.get(Worker, "Content Writer").status == WorkerStatus.ONLINE.value
    assert "password" not in launch.text.lower() and "traceback" not in mission["result_error"].lower()


def test_repurposing_waiting_worker_has_no_execution_or_provider_call(db_session, db_session_factory):
    _, repurposing = ready_runs(db_session)
    provider = Provider([success()])
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), provider, workers=False))
    first = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    second = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    assert first.status_code == second.status_code == 200 and first.json()["mission_status"] == "WAITING_FOR_WORKER"
    assert first.json()["mission_id"] == second.json()["mission_id"] and provider.calls == 0 and db_session.query(Execution).count() == 0
    assert db_session.get(ContentRepurposingRun, repurposing.id).status == "CREATED"


def test_rejected_editorial_decision_is_technical_success_and_responses_are_safe(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    api = client(db_session_factory, manager(db_session_factory, Provider([success("A customer says this is helpful.")]), Provider([success()])))
    response = api.post(f"/content/generation-runs/{generation.id}/launch")
    assert response.status_code == 200 and response.json()["result_success"] is True
    assert response.json()["result_data"]["evaluation_decision"] == "REJECTED"
    for forbidden in ("database_url", "etm_g5_database_url", "password", "api_key", "traceback", "engine", "session"):
        assert forbidden not in response.text.lower()


def test_openapi_has_exactly_the_six_frozen_content_operations():
    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    assert set(document["paths"]) == {
        "/content/generation-runs/{content_generation_run_id}/launch",
        "/content/repurposing-runs/{content_repurposing_run_id}/launch",
        "/content/missions/{mission_id}",
        "/content/generation-runs/{run_id}",
        "/content/repurposing-runs/{run_id}",
        "/content/artifacts/{artifact_id}",
    }
    assert inspect.getsource(router.__class__) is not None
