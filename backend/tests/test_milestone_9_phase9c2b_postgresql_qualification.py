"""Guarded PostgreSQL proof for M9C2B immutable facts and mutable control state."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import threading
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdMessageContent, ColdT3Decision
from app.models.cold_prospecting import ColdProspectingAuthorization, ColdProspectingPolicySelection
from app.models.crm import SuppressionEvent
from app.models.execution import Execution
from app.models.worker import Worker
from app.outreach.contracts import OutreachError, PreparedOutreachMessage, sha256_fingerprint
from app.crm.contracts import ContactPointProvenanceInput, ContactPointStateEventInput, SuppressionEventInput
from app.outreach.cold_b2b_contracts import CreateColdProspectingAuthorizationRequest, OrganizationEvidenceAuthorityReference, PolicySelectionAuthorityReference
from app.services.cold_prospecting_authority_registration_service import ColdProspectingAuthorityRegistrationService
from app.services.cold_prospecting_authorization_service import ColdProspectingAuthorizationService
from app.services.cold_delivery_t3_service import ColdDeliveryT3Service
from app.outreach.cold_recipient_resolution import ColdRecipientResolutionService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.suppression_service import SuppressionService
from app.outreach.cold_delivery_runtime_contracts import ColdDeliveryWorkflowPayload, cold_delivery_mission_key
from app.services.cold_delivery_mission_launch_service import ColdDeliveryMissionLaunchService
from app.services.cold_delivery_operation_service import ColdDeliveryOperationCreation, ColdDeliveryOperationService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.workflows.cold_delivery_workflow import ColdDeliveryWorkflow
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService


HEAD, PRIOR = "e0f1a2b3c4d5", "d3e4f5a6b7c8"
NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
RAW = os.getenv("ETM_G5_DATABASE_URL")
if not RAW:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
URL = make_url(RAW)
if not (URL.drivername.startswith("postgresql") and URL.database == "etm_g5_m9c2b3_qualification"):
    raise RuntimeError("M9C2B3 permits only ETM_G5_DATABASE_URL for etm_g5_m9c2b3_qualification.")


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


def _ready_t3(db, *, content_fingerprint="e" * 64):
    facts_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    at = facts_at + timedelta(seconds=2)
    subject = AudienceFoundationService(db).create_subject("ORGANIZATION")
    lead = LeadService(db).create_or_reuse(subject.id).record
    raw_email = f"m9c2b3-{uuid4().hex}@example.com"
    point = ContactPointService(db).create_or_reuse(lead.id, kind="EMAIL", normalized_value=raw_email).record
    ContactPointService(db).append_state_event(point.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", facts_at, "b3", uuid4().hex))
    ContactPointService(db).attach_provenance(point.id, ContactPointProvenanceInput("PUBLIC_BUSINESS_SOURCE", "b3", uuid4().hex, facts_at, facts_at, evidence_fingerprint="a" * 64))
    registration = ColdProspectingAuthorityRegistrationService(db)
    org, _ = registration.register_organization_evidence(lead_id=lead.id, source_namespace="b3-org", source_event_key=sha256_fingerprint({"org": uuid4().hex}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="b" * 64, evidence_fingerprint="c" * 64, evaluated_at=at)
    policy, _ = registration.register_policy_selection(lead_id=lead.id, source_namespace="b3-policy", source_event_key=sha256_fingerprint({"policy": uuid4().hex}), evidence_fingerprint="d" * 64, profile_key="cold-b2b-default-v1", evaluated_at=at)
    request = CreateColdProspectingAuthorizationRequest(lead.id, point.id, "cold_b2b:hosting", "INITIAL", "b3", sha256_fingerprint({"authorization": uuid4().hex}), OrganizationEvidenceAuthorityReference(org.id, org.evidence_fingerprint), PolicySelectionAuthorityReference(policy.id, policy.decision_fingerprint), "e" * 64, at)
    authorization, _ = ColdProspectingAuthorizationService(db).create_or_reuse(request)
    assert authorization.authorization_state == "ELIGIBLE", authorization.reason_codes
    operation = ColdDeliveryOperation(cold_authorization_id=authorization.id, lead_id=lead.id, contact_point_id=point.id, action="INITIAL", purpose_key="cold_b2b:hosting", purpose_family="hosting", source_namespace="b3", source_event_key=sha256_fingerprint({"operation": uuid4().hex}), message_content_fingerprint=content_fingerprint, operation_schema_version="v1", created_at=NOW)
    db.add(operation); db.flush()
    execution = Execution(workflow_name="cold-b2b-delivery", status="RUNNING", lease_owner="b3-worker", lease_generation=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(execution); db.flush()
    db.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="READY", revision=2, next_event_sequence=2, active_execution_id=str(execution.id), active_fence_identity="b3-worker:1", updated_at=NOW))
    db.commit()
    return operation, ExecutionLeaseAuthority(execution.id, "b3-worker", 1), raw_email


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


def test_t3_recipient_constraint_and_operation_authorization_ownership(db):
    operation = _operation(db)
    base = dict(
        operation_id=operation.id,
        cold_authorization_id=operation.cold_authorization_id,
        authorization_fingerprint="a" * 64,
        evaluated_at=NOW,
        policy_fingerprint="b" * 64,
        authority_fingerprint="c" * 64,
        crm_evidence_ids=[],
        decision_schema_version="cold-t3-decision-v1",
        source_namespace="m9c2b3-pg",
    )
    db.add(ColdT3Decision(**base, recipient_fingerprint=None, decision="BLOCKED", reason_codes=["POLICY_DENIED"], source_event_key="blocked"))
    db.commit()
    with db.bind.connect() as connection:
        with pytest.raises(Exception):
            connection.execute(text("UPDATE cold_t3_decisions SET decision='ALLOWED' WHERE source_event_key='blocked'"))
        connection.rollback()
        with pytest.raises(Exception):
            connection.execute(text("DELETE FROM cold_t3_decisions WHERE source_event_key='blocked'"))
        connection.rollback()
    db.add(ColdT3Decision(**base, recipient_fingerprint=None, decision="ALLOWED", reason_codes=["T3_ALLOWED"], source_event_key="allowed-null"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
    other = _authorization(db, "other")
    db.add(ColdT3Decision(**{**base, "cold_authorization_id": other.id}, recipient_fingerprint="d" * 64, decision="ALLOWED", reason_codes=["T3_ALLOWED"], source_event_key="cross-binding"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_t3_success_mismatch_and_recipient_timing(db, monkeypatch):
    operation, authority, raw_email = _ready_t3(db)
    calls = []
    original = ColdRecipientResolutionService.resolve_email
    def observed(**kwargs):
        calls.append(1)
        return original(**kwargs)
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", observed)
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    assert result["decision"] == "ALLOWED" and result["state"] == "DISPATCH_PLANNED" and len(calls) == 1
    decision = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
    event = db.query(ColdDeliveryEvent).filter_by(operation_id=operation.id).one()
    assert decision.recipient_fingerprint and raw_email not in str(decision.__dict__) and raw_email not in str(event.safe_payload) and raw_email not in str(result)

    operation, authority, _ = _ready_t3(db, content_fingerprint="f" * 64)
    calls.clear()
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    decision = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
    assert result["state"] == "T3_BLOCKED" and decision.recipient_fingerprint is None and calls == []


def test_t3_recipient_failure_and_committed_suppression(db, monkeypatch):
    operation, authority, _ = _ready_t3(db)
    def failing(**kwargs): raise OutreachError("RECIPIENT_RESOLUTION_FAILED", "safe failure")
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", failing)
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    decision = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
    assert result["state"] == "T3_BLOCKED" and "RECIPIENT_RESOLUTION_FAILED" in decision.reason_codes and decision.recipient_fingerprint is None

    operation, authority, _ = _ready_t3(db)
    SuppressionService(db).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc) - timedelta(seconds=1), "b3", uuid4().hex)); db.commit()
    calls = []
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", lambda **kwargs: calls.append(1))
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    decision = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
    assert result["state"] == "T3_BLOCKED" and decision.recipient_fingerprint is None and calls == []


def test_t3_same_authority_concurrency_and_stale_handoff(db, engine, monkeypatch):
    operation, authority, _ = _ready_t3(db)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    start, calls, outcomes, errors = threading.Barrier(3), [], [], []
    original = ColdRecipientResolutionService.resolve_email
    def observed(**kwargs):
        calls.append(1)
        return original(**kwargs)
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", observed)
    def worker():
        session = factory()
        try:
            start.wait(15); outcomes.append(ColdDeliveryT3Service(session).evaluate_and_plan(operation.id, authority))
        except Exception as error:
            session.rollback(); errors.append(error)
        finally: session.close()
    first, second = threading.Thread(target=worker), threading.Thread(target=worker)
    first.start(); second.start(); start.wait(15); first.join(30); second.join(30)
    assert not first.is_alive() and not second.is_alive() and len(outcomes) == 1 and len(errors) == 1
    assert isinstance(errors[0], OutreachError) and errors[0].category == "T3_STATE_UNAVAILABLE" and len(calls) == 1
    db.expire_all(); assert db.query(ColdT3Decision).filter_by(operation_id=operation.id).count() == db.query(ColdDeliveryEvent).filter_by(operation_id=operation.id).count() == 1

    operation, authority, _ = _ready_t3(db)
    db.query(Execution).filter_by(id=authority.execution_id).update({"lease_owner": "successor", "lease_generation": 2}); db.commit()
    db.query(ColdDeliveryOperationState).filter_by(operation_id=operation.id).update({"active_fence_identity": "successor:2"}); db.commit()
    calls.clear()
    with pytest.raises(Exception): ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    db.rollback()
    assert calls == [] and db.query(ColdT3Decision).filter_by(operation_id=operation.id).count() == 0
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, ExecutionLeaseAuthority(authority.execution_id, "successor", 2))
    assert result["state"] == "DISPATCH_PLANNED"


@pytest.mark.parametrize("failure_point", ("before_state", "event", "commit"))
def test_t3_failure_injection_rolls_back_all_facts(db, monkeypatch, failure_point):
    operation, authority, _ = _ready_t3(db)
    if failure_point == "before_state":
        original_execute = db.execute
        def fail_state(statement, *args, **kwargs):
            if "UPDATE cold_delivery_operation_state" in str(statement):
                raise RuntimeError("injected after decision flush")
            return original_execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, "execute", fail_state)
    elif failure_point == "event":
        original = db.add
        def fail_event(value):
            if isinstance(value, ColdDeliveryEvent): raise RuntimeError("injected event failure")
            return original(value)
        monkeypatch.setattr(db, "add", fail_event)
    else:
        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("injected commit failure")))
    with pytest.raises(RuntimeError): ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    db.rollback(); db.expire_all()
    state = db.get(ColdDeliveryOperationState, operation.id)
    assert state.current_state == "READY" and state.revision == 2
    assert db.query(ColdT3Decision).filter_by(operation_id=operation.id).count() == 0
    assert db.query(ColdDeliveryEvent).filter_by(operation_id=operation.id).count() == 0


def test_t3_suppression_writer_waits_for_production_contact_lock(db, engine, monkeypatch):
    operation, authority, _ = _ready_t3(db)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    resolver_entered, release_t3, writer_started, writer_done = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    outcome, errors, writer_result, ordering = [], [], {}, []
    original = ColdRecipientResolutionService.resolve_email
    def paused(**kwargs):
        resolver_entered.set(); ordering.append("t3_lock_acquired"); assert release_t3.wait(15)
        return original(**kwargs)
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", paused)
    def run_t3():
        session = factory()
        try: outcome.append(ColdDeliveryT3Service(session).evaluate_and_plan(operation.id, authority))
        except Exception as error: session.rollback(); errors.append(error)
        finally: session.close()
    def writer():
        session = factory()
        try:
            source_key = uuid4().hex; writer_result["source_key"] = source_key
            writer_started.set(); ordering.append("suppression_insert_attempt")
            result = SuppressionService(session).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc), "b3-race", source_key))
            session.commit(); writer_result["id"] = result.record.id; ordering.append("suppression_commit")
        except Exception as error: writer_result["error"] = error
        finally: writer_done.set(); session.close()
    t3 = threading.Thread(target=run_t3); t3.start(); assert resolver_entered.wait(15)
    suppressed = threading.Thread(target=writer); suppressed.start(); assert writer_started.wait(15)
    assert not writer_done.wait(0.5), "suppression writer unexpectedly bypassed T3 lead/contact locks"
    release_t3.set(); t3.join(30); ordering.append("t3_commit_release"); suppressed.join(30)
    assert errors == [] and outcome[0]["state"] == "DISPATCH_PLANNED" and writer_done.is_set() and "error" not in writer_result
    verify = factory()
    try: assert verify.query(SuppressionEvent).filter_by(id=writer_result["id"]).one().source_event_key == writer_result["source_key"]
    finally: verify.close()
    assert ordering.index("t3_lock_acquired") < ordering.index("suppression_insert_attempt") < ordering.index("t3_commit_release") < ordering.index("suppression_commit")


def _mutated_ready_t3(db, mutation):
    operation, authority, _ = _ready_t3(db)
    original = db.get(ColdProspectingAuthorization, operation.cold_authorization_id)
    values = {column.name: getattr(original, column.name) for column in ColdProspectingAuthorization.__table__.columns if column.name not in {"id", "recorded_at"}}
    values["source_namespace"] = "b3-mutated"; values["source_event_key"] = sha256_fingerprint({"mutation": mutation, "key": uuid4().hex})
    values["evidence"] = dict(values["evidence"])
    if mutation == "organization_id":
        registration = ColdProspectingAuthorityRegistrationService(db)
        other, _ = registration.register_organization_evidence(lead_id=original.lead_id, source_namespace="b3-other-org", source_event_key=sha256_fingerprint({"org": uuid4().hex}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="b" * 64, evidence_fingerprint="d" * 64, evaluated_at=original.evaluated_at)
        assert other.id != original.organization_evidence_id; values["organization_evidence_id"] = other.id
    elif mutation == "organization_fingerprint": values["evidence"]["organization_evidence_fingerprint"] = "f" * 64
    elif mutation == "policy_id":
        registration = ColdProspectingAuthorityRegistrationService(db)
        other, _ = registration.register_policy_selection(lead_id=original.lead_id, source_namespace="b3-other-policy", source_event_key=sha256_fingerprint({"policy": uuid4().hex}), evidence_fingerprint="e" * 64, profile_key="cold-b2b-default-v1", evaluated_at=original.evaluated_at)
        assert other.id != original.policy_selection_id; values["policy_selection_id"] = other.id
    elif mutation == "policy_fingerprint": values["evidence"]["policy_selection_fingerprint"] = "f" * 64
    elif mutation in {"profile_key", "profile_version"}:
        policy = db.get(ColdProspectingPolicySelection, original.policy_selection_id)
        policy_values = {column.name: getattr(policy, column.name) for column in ColdProspectingPolicySelection.__table__.columns if column.name not in {"id", "recorded_at"}}
        policy_values["source_namespace"] = "b3-mutated-policy"; policy_values["source_event_key"] = sha256_fingerprint({"policy": mutation, "key": uuid4().hex})
        policy_values["profile_key" if mutation == "profile_key" else "profile_version"] = "other-profile-value"
        replacement = ColdProspectingPolicySelection(**policy_values); db.add(replacement); db.flush(); values["policy_selection_id"] = replacement.id
    elif mutation == "provenance_ids": values["evidence"]["provenance_ids"] = []
    elif mutation == "provenance_fingerprint": values["evidence"]["provenance_fingerprints"] = ["f" * 64]
    elif mutation == "provenance_missing": values["evidence"]["provenance_ids"] = []
    clone = ColdProspectingAuthorization(**values); db.add(clone); db.flush()
    # immutable operation cannot be rewritten: use a fresh persisted operation/state bound to the clone.
    new = ColdDeliveryOperation(cold_authorization_id=clone.id, lead_id=operation.lead_id, contact_point_id=operation.contact_point_id, action=operation.action, purpose_key=operation.purpose_key, purpose_family=operation.purpose_family, source_namespace="b3-mutated", source_event_key=sha256_fingerprint({"operation": uuid4().hex}), message_content_fingerprint=operation.message_content_fingerprint, operation_schema_version="v1", created_at=NOW)
    db.add(new); db.flush(); db.add(ColdDeliveryOperationState(operation_id=new.id, current_state="READY", revision=2, next_event_sequence=2, active_execution_id=str(authority.execution_id), active_fence_identity="b3-worker:1", updated_at=NOW)); db.commit()
    return new, authority


@pytest.mark.parametrize("mutation", ("organization_id", "organization_fingerprint", "policy_id", "policy_fingerprint", "profile_key", "profile_version", "provenance_ids", "provenance_fingerprint", "provenance_missing"))
def test_t3_persisted_commitment_mutations_fail_closed(db, monkeypatch, mutation):
    operation, authority = _mutated_ready_t3(db, mutation)
    calls = []
    monkeypatch.setattr(ColdRecipientResolutionService, "resolve_email", lambda **kwargs: calls.append(1))
    result = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
    fact = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
    assert result["state"] == "T3_BLOCKED" and fact.recipient_fingerprint is None and calls == []


def test_t3_state_cas_rejects_second_writer_with_same_expected_revision(db, engine):
    operation, authority, _ = _ready_t3(db); fence = "b3-worker:1"
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False); left, right = factory(), factory()
    try:
        assert left.execute(text("select pg_backend_pid()")).scalar_one() != right.execute(text("select pg_backend_pid()")).scalar_one()
        expected = left.get(ColdDeliveryOperationState, operation.id).revision; assert right.get(ColdDeliveryOperationState, operation.id).revision == expected
        where = (ColdDeliveryOperationState.operation_id == operation.id, ColdDeliveryOperationState.revision == expected, ColdDeliveryOperationState.active_execution_id == str(authority.execution_id), ColdDeliveryOperationState.active_fence_identity == fence)
        first = left.execute(update(ColdDeliveryOperationState).where(*where).values(current_state="DISPATCH_PLANNED", revision=expected + 1)).rowcount; left.commit()
        second = right.execute(update(ColdDeliveryOperationState).where(*where).values(current_state="DISPATCH_PLANNED", revision=expected + 1)).rowcount; right.rollback()
    finally: left.close(); right.close()
    verify = factory()
    try: assert first == 1 and second == 0 and verify.query(ColdT3Decision).filter_by(operation_id=operation.id).count() == verify.query(ColdDeliveryEvent).filter_by(operation_id=operation.id).count() == 0
    finally: verify.close()
