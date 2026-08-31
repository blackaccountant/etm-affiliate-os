"""Durable Mission identity, payload, activation, and workflow-session proofs."""

import json
from datetime import datetime, timezone

from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.outreach.delivery_mission_contracts import (
    OUTREACH_DELIVERY_CAPABILITY,
    OutreachDeliveryWorkflowPayload,
    outreach_delivery_mission_idempotency_key,
)
from app.repositories.worker_repository import WorkerRepository
from app.services.outreach_delivery_mission_launch_service import OutreachDeliveryMissionLaunchService
from app.workforce.manager import WorkforceManager


def seed_prepared(db, attempt_id="11111111-1111-1111-1111-111111111111"):
    now = datetime.now(timezone.utc)
    attempt = OutreachDeliveryAttempt(
        id=attempt_id, outreach_intent_id="intent", attempt_number=1,
        source_namespace="test", source_event_key=attempt_id, request_fingerprint="a" * 64,
    )
    event = OutreachDeliveryEvent(
        delivery_attempt_id=attempt_id, sequence_number=1, event_type="PREPARED", occurred_at=now,
        source_namespace="test", source_event_key=f"prepared-{attempt_id}", event_fingerprint="b" * 64,
        safe_payload={},
    )
    db.add_all([attempt, event]); db.commit(); return attempt


def persist_real_default_workforce(db):
    workforce = WorkforceManager(load_defaults=True)
    repository = WorkerRepository(db)
    for worker in workforce.workers():
        repository.ensure(worker)
    return workforce


def test_mission_contract_is_exact_durable_id_only():
    attempt_id = "11111111-1111-1111-1111-111111111111"
    payload = OutreachDeliveryWorkflowPayload(attempt_id)
    assert payload.to_dict() == {"delivery_attempt_id": attempt_id}
    assert outreach_delivery_mission_idempotency_key(attempt_id) == f"outreach-delivery:{attempt_id}"
    text = repr(payload.to_dict()).lower()
    assert not {"recipient", "provider", "secret", "session", "execution_id"}.intersection(payload.to_dict())
    assert "@" not in text


def test_same_attempt_activates_through_real_default_workforce_and_reuses_operation(
    monkeypatch, db_session, db_session_factory,
):
    attempt = seed_prepared(db_session)
    workforce = persist_real_default_workforce(db_session)
    eligible = [
        worker for worker in workforce.workers()
        if worker.has_capability(OUTREACH_DELIVERY_CAPABILITY)
    ]
    provider_calls = []
    monkeypatch.setattr(
        "app.outreach.providers.resend.ResendEmailProvider.send",
        lambda *_args, **_kwargs: provider_calls.append(True),
    )
    launcher = OutreachDeliveryMissionLaunchService(db_session_factory)
    first = launcher.launch(attempt.id); second = launcher.launch(attempt.id)
    mission = db_session.get(MissionRecord, first.mission_id)
    execution = db_session.query(Execution).filter_by(mission_id=mission.id).one()
    assert OUTREACH_DELIVERY_CAPABILITY == launcher.required_capability == "outreach_delivery"
    assert [worker.name for worker in eligible] == ["Content Writer"]
    assert execution.worker_name == mission.current_worker_name == "Content Writer"
    assert mission.workflow_name == "outreach_delivery"
    assert mission.required_capability == "outreach_delivery"
    assert first.created is True and second.created is False and first.mission_id == second.mission_id
    assert json.loads(mission.input_data) == {"delivery_attempt_id": attempt.id}
    assert mission.idempotency_key == f"outreach-delivery:{attempt.id}"
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 1
    assert provider_calls == []


def test_default_registry_and_workforce_enforce_least_privilege_outreach_capability():
    from app.registry.default_workflows import create_workflow_registry
    workforce = WorkforceManager(load_defaults=True)
    workers = {worker.name: worker for worker in workforce.workers()}
    eligible = [
        worker for worker in workers.values()
        if worker.has_capability(OUTREACH_DELIVERY_CAPABILITY)
    ]
    names = list(create_workflow_registry().all())
    assert names.count("outreach_delivery") == 1
    assert [worker.name for worker in eligible] == ["Content Writer"]
    assert all(worker.has_capability("outreach_delivery") for worker in eligible)
    assert workers["Content Writer"].capabilities == [
        "content_generation", "content_distribution", "outreach_delivery",
        "seo_content", "product_reviews",
    ]
    assert workers["Product Hunter"].has_capability("outreach_delivery") is False
    assert workers["Research Agent"].has_capability("outreach_delivery") is False
    selected = workforce.assign_by_capability("Outreach delivery proof", "outreach_delivery")
    assert selected is workers["Content Writer"]
