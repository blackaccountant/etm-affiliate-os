"""Focused SQLite proofs for fenced ambiguous-publish recovery."""

from datetime import datetime, timedelta, timezone

import pytest

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import DistributionAdapterMetadata
from app.models.execution import Execution
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.services.content_distribution_reconciliation_mission_launch_service import (
    ContentDistributionReconciliationMissionLaunchService,
)
from app.services.execution_runtime_context import activate_execution_runtime_context
from app.workflows.distribution.distribution_publish_workflow import DistributionPublishWorkflow
from tests.test_milestone_5_phase5e1_distribution_reconciliation import (
    distribution_run,
    run_and_context,
)


class PublishProbe(DistributionAdapter):
    def __init__(self):
        self.publish_calls = 0

    @property
    def metadata(self):
        return DistributionAdapterMetadata("fake", True, True)

    def validate_target(self, request):
        raise AssertionError("PUBLISHING recovery must not validate")

    def publish(self, request):
        self.publish_calls += 1
        raise AssertionError("PUBLISHING recovery must never publish")


def workflow(factory, adapter):
    registry = DistributionAdapterRegistry()
    registry.register(adapter)
    return DistributionPublishWorkflow(factory, registry)


def test_direct_publishing_invocation_cannot_publish_or_convert(db_session, db_session_factory):
    run = distribution_run(db_session, status="PUBLISHING")
    adapter = PublishProbe()
    result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    assert not result.success and adapter.publish_calls == 0
    assert db_session.get(type(run), run.id).status == "PUBLISHING"


def test_recovered_publishing_attempt_hands_off_without_publish(db_session, db_session_factory):
    run = distribution_run(db_session, status="PUBLISHING")
    _, context = run_and_context(db_session, workflow="distribution_publish", recovery=True)
    adapter = PublishProbe()
    with activate_execution_runtime_context(context):
        result = workflow(db_session_factory, adapter).execute({"distribution_run_id": run.id})
    db_session.expire_all()
    assert result.success and result.data["reconciliation_required"] is True
    assert db_session.get(type(run), run.id).status == "RECONCILIATION_REQUIRED"
    assert adapter.publish_calls == 0


def test_stale_authority_cannot_handoff_publishing_business_state(db_session, db_session_factory):
    run = distribution_run(db_session, status="PUBLISHING")
    mission, context = run_and_context(db_session, workflow="distribution_publish", recovery=True)
    original = db_session.get(Execution, context.authority.execution_id)
    original.status = "ABANDONED"
    original.lease_expires_at = None
    replacement = Execution(
        mission_id=mission.id,
        mission_name=mission.name,
        worker_name="Worker",
        workflow_name="distribution_publish",
        status="RUNNING",
        lease_owner="replacement",
        lease_generation=context.authority.lease_generation + 1,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(replacement)
    db_session.commit()
    with activate_execution_runtime_context(context), pytest.raises(ExecutionLeaseLostError):
        workflow(db_session_factory, PublishProbe()).execute({"distribution_run_id": run.id})
    assert db_session.get(type(run), run.id).status == "PUBLISHING"


def test_reconciliation_launcher_cannot_convert_publishing(db_session, db_session_factory):
    run = distribution_run(db_session, status="PUBLISHING")
    launcher = ContentDistributionReconciliationMissionLaunchService(session_factory=db_session_factory)
    with pytest.raises(RuntimeError, match="reconciliation-required"):
        launcher.launch(run.id)
    assert db_session.get(type(run), run.id).status == "PUBLISHING"
