"""Trust-boundary checks for owned lifecycle participants."""

import pytest

from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.execution_service import ExecutionService
from app.services.owned_lifecycle_participants import (
    OwnedLifecycleParticipantRegistry,
    participant_for_workflow,
)
from app.repositories.execution_repository import ExecutionRepository
from app.workflow_engine.workflow_result import WorkflowResult


def test_workflow_callback_data_is_never_selected_as_a_participant():
    called = []
    result = WorkflowResult(False, "unregistered", {}, errors=["safe"])
    result._lifecycle_transition = lambda *args: called.append(True)
    assert "_lifecycle_transition" not in ExecutionAttemptRunner._normalize(result, None)
    assert participant_for_workflow("unregistered") is None and called == []


def test_registry_rejects_duplicate_registration_and_unknown_workflows():
    registry = OwnedLifecycleParticipantRegistry()
    participant = object()
    registry.register("trusted", participant)
    assert registry.get("trusted") is participant and registry.get("unknown") is None
    with pytest.raises(ValueError):
        registry.register("trusted", object())


def test_publish_participant_is_selected_only_from_durable_workflow_identity():
    assert participant_for_workflow("distribution_publish") is not None
    assert participant_for_workflow("workflow_output_claim") is None


def test_legacy_unfenced_retry_claim_api_is_not_exposed():
    assert not hasattr(ExecutionRepository, "claim_retry")
    assert not hasattr(ExecutionService, "claim_retry")
