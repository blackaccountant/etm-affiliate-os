"""Guarded PostgreSQL proof for M9C2B immutable facts and mutable control state."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import threading
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdMessageContent
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.models.execution import Execution
from app.models.worker import Worker
from app.outreach.contracts import OutreachError, PreparedOutreachMessage, sha256_fingerprint
from app.outreach.cold_delivery_runtime_contracts import ColdDeliveryWorkflowPayload, cold_delivery_mission_key
from app.services.cold_delivery_mission_launch_service import ColdDeliveryMissionLaunchService
from app.services.cold_delivery_operation_service import ColdDeliveryOperationCreation, ColdDeliveryOperationService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.workflows.cold_delivery_workflow import ColdDeliveryWorkflow
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService


HEAD, PRIOR = "d3e4f5a6b7c8", "c2d3e4f5a6b7"
NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
RAW = os.getenv("ETM_G5_DATABASE_URL")
if not RAW:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
URL = make_url(RAW)
if not (URL.drivername.startswith("postgresql") and URL.database == "etm_g5_m9c2b2_qualification"):
    raise RuntimeError("M9C2B2 permits only ETM_G5_DATABASE_URL for etm_g5_m9c2b2_qualification.")


@pytest.fixture(scope="module")
def engine():
    previous = settings.DATABASE_URL; settings.DATABASE_URL = URL.render_as_string(hide_password=False)
    result = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        command.upgrade(Config("alembic.ini"), HEAD); yield result
    finally:
        settings.DATABASE_URL = previous; result.dispose()


@pytest.fixture
def db(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE cold_provider_feedback_receipts, cold_provider_dispatch_references, cold_provider_dispatches, cold_t3_decisions, cold_delivery_events, cold_delivery_operation_state, cold_message_contents, cold_delivery_operations, executions, missions, workers, cold_prospecting_authorizations CASCADE"))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try: yield session
    finally: session.close()


def _authorization(db, source=None):
    source = source or uuid4().hex
    subject = AudienceFoundationService(db).create_subject("ORGANIZATION")
    lead = LeadService(db).create_or_reuse(subject.id).record
    point = ContactPointService(db).create_or_reuse(lead.id, kind="EMAIL", normalized_value=f"m9c2b-{uuid4().hex}@example.com").record
    auth = ColdProspectingAuthorization(lead_id=lead.id, contact_point_id=point.id, organization_evidence_id=None, policy_selection_id=None, channel="EMAIL", purpose_key="cold_b2b:platform", purpose_family="platform", requested_action="INITIAL", source_namespace="m9c2b-pg", source_event_key=sha256_fingerprint({"authorization": source}), request_fingerprint="b" * 64, authorization_state="ELIGIBLE", reason_codes=["ELIGIBLE"], eligibility_policy_version="v1", frequency_policy_version="v1", policy_profile_key="profile", decision_fingerprint="c" * 64, evidence={}, evaluated_at=NOW)
    db.add(auth); db.flush(); db.commit()
    return auth


def _operation(db):
    auth = _authorization(db)
    operation = ColdDeliveryOperation(cold_authorization_id=auth.id, lead_id=auth.lead_id, contact_point_id=auth.contact_point_id, action="INITIAL", purpose_key="cold_b2b:platform", purpose_family="platform", source_namespace="m9c2b-pg", source_event_key="d" * 64, message_content_fingerprint="e" * 64, operation_schema_version="v1", created_at=NOW)
    db.add(operation); db.flush(); db.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="CREATED", revision=1, next_event_sequence=1, updated_at=NOW)); db.commit(); return operation


def _request(auth, source="source", body="Bounded reusable copy"):
    return ColdDeliveryOperationCreation(auth.id, "m9c2b2-pg", sha256_fingerprint({"source": source}), PreparedOutreachMessage(body, subject="A bounded subject"))


def _create(factory, request, outcomes, errors, start):
    db = factory()
    try:
        start.wait(15)
        result = ColdDeliveryOperationService(db).create_or_reuse(request)
        db.commit(); outcomes.append((result.operation.id, result.reused))
    except Exception as error:
        db.rollback(); errors.append(error)
    finally:
        db.close()


def test_postgresql_atomic_operation_creation_replay_conflict_and_rollback(db, engine, monkeypatch):
    auth = _authorization(db)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    request = _request(auth, "same")
    outcomes, errors, start = [], [], threading.Barrier(3)
    threads = [threading.Thread(target=_create, args=(factory, request, outcomes, errors, start)) for _ in range(2)]
    for thread in threads: thread.start()
    start.wait(15)
    for thread in threads: thread.join(30); assert not thread.is_alive()
    assert errors == [] and len({item[0] for item in outcomes}) == 1 and sorted(item[1] for item in outcomes) == [False, True]
    assert db.query(ColdDeliveryOperation).count() == db.query(ColdMessageContent).count() == db.query(ColdDeliveryOperationState).count() == 1
    conflicting_outcomes, conflicting_errors, conflicting_start = [], [], threading.Barrier(3)
    conflicting_auth = _authorization(db, "conflict")
    conflicting = [_request(conflicting_auth, "conflict", body) for body in ("Winner copy", "Conflicting copy")]
    threads = [threading.Thread(target=_create, args=(factory, item, conflicting_outcomes, conflicting_errors, conflicting_start)) for item in conflicting]
    for thread in threads: thread.start()
    conflicting_start.wait(15)
    for thread in threads: thread.join(30); assert not thread.is_alive()
    assert len(conflicting_outcomes) == 1 and len(conflicting_errors) == 1
    assert isinstance(conflicting_errors[0], OutreachError) and conflicting_errors[0].category == "IDEMPOTENCY_CONFLICT"
    rollback_auth = _authorization(db, "rollback")
    real_flush, flushes = db.flush, [0]
    def fail_during_content_and_state(*args, **kwargs):
        flushes[0] += 1
        if flushes[0] == 2: raise RuntimeError("forced content/state failure")
        return real_flush(*args, **kwargs)
    monkeypatch.setattr(db, "flush", fail_during_content_and_state)
    with pytest.raises(RuntimeError, match="forced content/state failure"):
        ColdDeliveryOperationService(db).create_or_reuse(_request(rollback_auth, "rollback"))
    monkeypatch.setattr(db, "flush", real_flush); db.rollback()
    assert db.query(ColdDeliveryOperation).filter_by(source_event_key=sha256_fingerprint({"source": "rollback"})).count() == 0


def test_postgresql_mission_launch_capability_and_runtime_fence(db, engine):
    operation = _operation(db)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="no eligible worker"):
        ColdDeliveryMissionLaunchService(factory).launch(operation.id)
    db.add(Worker(name="Cold Delivery Orchestrator", worker_type="AI Agent", capabilities=["cold_b2b_delivery"], status="ONLINE")); db.commit()
    launch = ColdDeliveryMissionLaunchService(factory)
    results, errors, start = [], [], threading.Barrier(3)
    def launch_one():
        try: start.wait(15); results.append(launch.launch(operation.id))
        except Exception as error: errors.append(error)
    threads = [threading.Thread(target=launch_one) for _ in range(2)]
    for thread in threads: thread.start()
    start.wait(15)
    for thread in threads: thread.join(30); assert not thread.is_alive()
    assert errors == [] and len({result[0].mission_id for result in results}) == 1 and sorted(result[1] for result in results) == [False, True]
    mission = results[0][0]
    assert mission.spec.payload == {"cold_delivery_operation_id": operation.id} and mission.spec.idempotency_key == cold_delivery_mission_key(operation.id)
    execution = db.get(Execution, mission.execution_id)
    authority = ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)
    workflow = ColdDeliveryWorkflow(factory)
    # Handoff before the B2 state transition: stale authority must neither
    # mutate the state nor append its authoritative event, while the new fence may.
    db.query(Execution).filter_by(id=execution.id).update({"lease_owner": "new-owner", "lease_generation": authority.lease_generation + 1}); db.commit()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, mission.mission_id)):
        assert workflow.execute(ColdDeliveryWorkflowPayload(operation.id).to_dict()).success is False
    assert db.get(ColdDeliveryOperationState, operation.id).current_state == "CREATED"
    assert db.query(ColdDeliveryEvent).filter_by(operation_id=operation.id).count() == 0
    successor = ExecutionLeaseAuthority(execution.id, "new-owner", authority.lease_generation + 1)
    with activate_execution_runtime_context(ExecutionRuntimeContext(successor, mission.mission_id)):
        assert workflow.execute(ColdDeliveryWorkflowPayload(operation.id).to_dict()).success is True
    state = db.get(ColdDeliveryOperationState, operation.id)
    assert (state.current_state, state.revision, state.active_execution_id) == ("READY", 2, str(execution.id))
    assert db.query(ColdDeliveryEvent).filter_by(operation_id=operation.id, event_type="RUNTIME_READY").count() == 1
    before_events = db.query(ColdDeliveryEvent).count()
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, mission.mission_id)):
        result = workflow.execute(ColdDeliveryWorkflowPayload(operation.id).to_dict())
    assert result.success is False and db.get(ColdDeliveryOperationState, operation.id).current_state == "READY"
    assert db.query(ColdDeliveryEvent).count() == before_events


def test_append_only_trigger_composite_content_fk_and_mutable_state(db, engine):
    operation = _operation(db)
    db.add(ColdMessageContent(operation_id=operation.id, content_fingerprint="e" * 64, subject=None, body="bounded content", content_format="TEXT", content_schema_version="v1", created_at=NOW)); db.commit()
    with engine.connect() as connection:
        with pytest.raises(Exception): connection.execute(text("UPDATE cold_delivery_operations SET purpose_family='changed' WHERE id=:id"), {"id": operation.id})
        connection.rollback()
        with pytest.raises(Exception): connection.execute(text("DELETE FROM cold_delivery_operations WHERE id=:id"), {"id": operation.id})
        connection.rollback()
        with pytest.raises(Exception): connection.execute(text("INSERT INTO cold_message_contents (id, operation_id, content_fingerprint, body, content_format, content_schema_version, created_at) VALUES ('f0000000-0000-0000-0000-000000000000', :id, :fingerprint, 'different', 'TEXT', 'v1', :now)"), {"id": operation.id, "fingerprint": "f" * 64, "now": NOW})
        connection.rollback()
        connection.execute(text("UPDATE cold_delivery_operation_state SET current_state='READY', revision=2 WHERE operation_id=:id"), {"id": operation.id}); connection.commit()
    db.expire_all(); assert db.get(ColdDeliveryOperationState, operation.id).current_state == "READY"


def test_migration_round_trip(engine):
    config = Config("alembic.ini")
    command.downgrade(config, PRIOR); command.upgrade(config, HEAD)
