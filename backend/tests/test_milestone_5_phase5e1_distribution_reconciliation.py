"""Focused SQLite proofs for recovery-safe distribution reconciliation."""

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import (
    DistributionAdapterMetadata,
    DistributionStatusLookupState,
    DistributionStatusResult,
)
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.content_distribution_reconciliation_mission_launch_service import (
    ContentDistributionReconciliationMissionLaunchService,
)
from app.services.distribution_run_service import DistributionRunService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import (
    ExecutionRuntimeContext,
    activate_execution_runtime_context,
)
from app.workflows.distribution.distribution_reconcile_workflow import DistributionReconcileWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request, source


class StatusAdapter(DistributionAdapter):
    def __init__(self, state, *, supports_lookup=True):
        self.state = state
        self.supports_lookup = supports_lookup
        self.publish_calls = 0
        self.lookup_calls = 0

    @property
    def metadata(self):
        return DistributionAdapterMetadata("fake", self.supports_lookup, True)

    def validate_target(self, request):
        raise AssertionError("reconciliation must not validate for publication")

    def publish(self, request):
        self.publish_calls += 1
        raise AssertionError("reconciliation must never publish")

    def get_publish_status(self, request):
        self.lookup_calls += 1
        now = datetime.now(timezone.utc)
        return DistributionStatusResult(
            self.state,
            external_post_id="post" if self.state is DistributionStatusLookupState.PUBLISHED else None,
            external_url="https://example.invalid/post" if self.state is DistributionStatusLookupState.PUBLISHED else None,
            published_at=now if self.state is DistributionStatusLookupState.PUBLISHED else None,
            safe_metadata={"platform_status": self.state.value.lower()},
        )


def run_and_context(db, *, workflow="distribution_reconcile", recovery=False):
    missions = MissionRepository(db)
    workers = WorkerRepository(db)
    executions = ExecutionRepository(db)
    mission = missions.create(str(uuid4()), "Reconcile", "reconcile", workflow, current_worker_name="Worker")
    missions.update_status(mission.id, "RUNNING", current_worker_name="Worker")
    workers.create("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)
    assert workers.claim("Worker", mission.id)
    execution = executions.create(workflow, "RUNNING", mission.id, mission.name, "Worker", input_data="{}")
    authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
    assert executions.acquire_lease(authority, 600)
    return mission, ExecutionRuntimeContext(authority, mission.id, recovery)


def workflow(factory, adapter):
    registry = DistributionAdapterRegistry()
    registry.register(adapter)
    return DistributionReconcileWorkflow(factory, registry)


def distribution_run(db, *, status="RECONCILIATION_REQUIRED"):
    source(db)
    run = DistributionRunService(db).create(request(platform="fake"))
    run.status = status
    db.commit()
    return run


def test_normal_claim_is_conditional_and_exactly_one_claimant(db_session, db_session_factory):
    run = distribution_run(db_session)
    _, context = run_and_context(db_session)
    repository = DistributionRunRepository(db_session)
    assert repository.claim_reconciliation(run.id, context.authority).status == "RECONCILING"
    assert repository.claim_reconciliation(run.id, context.authority) is None


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DistributionStatusLookupState.PUBLISHED, "COMPLETED"),
        (DistributionStatusLookupState.NOT_FOUND, "RECONCILING"),
        (DistributionStatusLookupState.UNKNOWN, "RECONCILIATION_REQUIRED"),
    ],
)
def test_reconciliation_outcomes_never_publish(db_session, db_session_factory, outcome, expected):
    run = distribution_run(db_session)
    _, context = run_and_context(db_session)
    adapter = StatusAdapter(outcome)
    with activate_execution_runtime_context(context):
        result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    db_session.expire_all()
    current = db_session.get(type(run), run.id)
    assert result.success and current.status == expected
    assert adapter.lookup_calls == 1 and adapter.publish_calls == 0
    if outcome is DistributionStatusLookupState.PUBLISHED:
        assert current.external_post_id == "post" and current.external_url


def test_unsupported_lookup_returns_manual_required_without_publish(db_session, db_session_factory):
    run = distribution_run(db_session)
    _, context = run_and_context(db_session)
    adapter = StatusAdapter(DistributionStatusLookupState.UNKNOWN, supports_lookup=False)
    with activate_execution_runtime_context(context):
        result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    db_session.expire_all()
    assert result.success and db_session.get(type(run), run.id).status == "RECONCILIATION_REQUIRED"
    assert result.data["reconciliation_state"] == "MANUAL_REQUIRED" and adapter.publish_calls == 0


def test_recovered_attempt_resumes_reconciling_without_second_claim(db_session, db_session_factory):
    run = distribution_run(db_session, status="RECONCILING")
    _, context = run_and_context(db_session, recovery=True)
    adapter = StatusAdapter(DistributionStatusLookupState.PUBLISHED)
    with activate_execution_runtime_context(context):
        result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    db_session.expire_all()
    assert result.success and db_session.get(type(run), run.id).status == "COMPLETED"
    assert adapter.lookup_calls == 1 and adapter.publish_calls == 0


def test_normal_attempt_cannot_resume_existing_reconciling_run(db_session, db_session_factory):
    run = distribution_run(db_session, status="RECONCILING")
    _, context = run_and_context(db_session)
    adapter = StatusAdapter(DistributionStatusLookupState.PUBLISHED)
    with activate_execution_runtime_context(context):
        result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    assert result.success and adapter.lookup_calls == adapter.publish_calls == 0
    assert db_session.get(type(run), run.id).status == "RECONCILING"


def test_reconciliation_mission_payload_stays_business_only(db_session, db_session_factory):
    run = distribution_run(db_session)
    WorkerRepository(db_session).create(
        "Reconciliation Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE,
    )
    manager = __import__("app.mission.manager", fromlist=["MissionManager"]).MissionManager(
        workforce=WorkforceManager(load_defaults=False), session_factory=db_session_factory,
    )
    launcher = ContentDistributionReconciliationMissionLaunchService(manager, db_session_factory)
    first = launcher.launch(run.id)
    second = launcher.launch(run.id)
    mission = db_session.get(MissionRecord, first.mission_id)
    assert first.mission_id == second.mission_id
    assert json.loads(mission.input_data) == {"distribution_run_id": run.id}


def test_runtime_context_is_not_persisted_in_mission_payload(db_session, db_session_factory):
    run = distribution_run(db_session)
    mission, context = run_and_context(db_session, recovery=True)
    adapter = StatusAdapter(DistributionStatusLookupState.UNKNOWN)
    with activate_execution_runtime_context(context):
        workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    assert db_session.get(MissionRecord, mission.id).input_data is None
