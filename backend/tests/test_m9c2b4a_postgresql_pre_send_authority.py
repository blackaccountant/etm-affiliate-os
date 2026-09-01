"""Guarded PostgreSQL qualification for M9C2B4A pre-send authority."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.crm.contracts import ContactPointProvenanceInput, ContactPointStateEventInput, PermissionEventInput, SuppressionEventInput
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdDispatchReservation, ColdT3Decision
from app.models.execution import Execution
from app.outreach.cold_b2b_contracts import (
    CreateColdProspectingAuthorizationRequest,
    OrganizationEvidenceAuthorityReference,
    PolicySelectionAuthorityReference,
)
from app.outreach.cold_provider_approval_contracts import ColdProviderApproval, ColdProviderApprovalRegistry
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.cold_delivery_pre_send_service import ColdDeliveryPreSendService
from app.services.cold_delivery_t3_service import ColdDeliveryT3Service
from app.services.cold_prospecting_authority_registration_service import ColdProspectingAuthorityRegistrationService
from app.services.cold_prospecting_authorization_service import ColdProspectingAuthorizationService
from app.services.contact_point_service import ContactPointService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


RAW_URL = os.getenv("ETM_G5_DATABASE_URL")
if not RAW_URL:
    pytest.skip("M9C2B4A requires explicit ETM_G5_DATABASE_URL", allow_module_level=True)
URL = make_url(RAW_URL)
if not (URL.drivername == "postgresql+psycopg2" and URL.host == "127.0.0.1"
        and URL.port == 5432 and URL.database == "etm_g5_m9c2b4a_qualification"):
    raise RuntimeError("M9C2B4A permits only the guarded etm_g5_m9c2b4a_qualification database")


@pytest.fixture(scope="module")
def factory():
    config = Config("alembic.ini")
    prior = settings.DATABASE_URL
    settings.DATABASE_URL = URL.render_as_string(hide_password=False)
    try:
        command.upgrade(config, "head")
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        settings.DATABASE_URL = prior
        engine.dispose()


def ready_for_reservation(factory, plan=True):
    db = factory()
    try:
        facts_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        at = facts_at + timedelta(seconds=2)
        subject = AudienceFoundationService(db).create_subject("ORGANIZATION")
        lead = LeadService(db).create_or_reuse(subject.id).record
        raw_recipient = f"m9c2b4a-distinctive-{uuid4().hex}@example.invalid"
        point = ContactPointService(db).create_or_reuse(lead.id, kind="EMAIL", normalized_value=raw_recipient).record
        contacts = ContactPointService(db)
        contacts.append_state_event(point.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", facts_at, "m9c2b4a", uuid4().hex))
        contacts.attach_provenance(point.id, ContactPointProvenanceInput("PUBLIC_BUSINESS_SOURCE", "m9c2b4a", uuid4().hex, facts_at, facts_at, evidence_fingerprint="a" * 64))
        db.commit()
        register = ColdProspectingAuthorityRegistrationService(db)
        org, _ = register.register_organization_evidence(lead_id=lead.id, source_namespace="m9c2b4a-org", source_event_key=sha256_fingerprint({"org": uuid4().hex}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="b" * 64, evidence_fingerprint="c" * 64, evaluated_at=at)
        policy, _ = register.register_policy_selection(lead_id=lead.id, source_namespace="m9c2b4a-policy", source_event_key=sha256_fingerprint({"policy": uuid4().hex}), evidence_fingerprint="d" * 64, profile_key="cold-b2b-default-v1", evaluated_at=at)
        request = CreateColdProspectingAuthorizationRequest(lead.id, point.id, "cold_b2b:hosting", "INITIAL", "m9c2b4a", sha256_fingerprint({"authorization": uuid4().hex}), OrganizationEvidenceAuthorityReference(org.id, org.evidence_fingerprint), PolicySelectionAuthorityReference(policy.id, policy.decision_fingerprint), "f" * 64, at)
        authorization, _ = ColdProspectingAuthorizationService(db).create_or_reuse(request)
        assert authorization.authorization_state == "ELIGIBLE", authorization.reason_codes
        operation = ColdDeliveryOperation(cold_authorization_id=authorization.id, lead_id=lead.id, contact_point_id=point.id, action="INITIAL", purpose_key="cold_b2b:hosting", purpose_family="hosting", source_namespace="m9c2b4a", source_event_key=sha256_fingerprint({"operation": uuid4().hex}), message_content_fingerprint="f" * 64, operation_schema_version="v1")
        execution = Execution(workflow_name="cold-b2b-delivery", status="RUNNING", lease_owner="m9c2b4a-worker", lease_generation=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add_all((operation, execution)); db.flush()
        db.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="READY", revision=1, next_event_sequence=1, active_execution_id=str(execution.id), active_fence_identity="m9c2b4a-worker:1"))
        db.commit()
        authority = ExecutionLeaseAuthority(execution.id, "m9c2b4a-worker", 1)
        if plan:
            t3 = ColdDeliveryT3Service(db).evaluate_and_plan(operation.id, authority)
            decision = db.query(ColdT3Decision).filter_by(operation_id=operation.id).one()
            assert t3["state"] == "DISPATCH_PLANNED", decision.reason_codes
        return operation.id, authority
    finally:
        db.close()


def valid_provider():
    return ColdProviderApproval("test-only", "test-v1")


def reserve(factory, operation_id, authority, approval=None):
    db = factory()
    try:
        return ColdDeliveryPreSendService(
            db, ColdProviderApprovalRegistry((approval or valid_provider(),))
        ).reserve(operation_id, authority)
    finally:
        db.close()


def persisted(factory, operation_id):
    db = factory()
    try:
        state = db.get(ColdDeliveryOperationState, operation_id)
        reservations = db.query(ColdDispatchReservation).filter_by(operation_id=operation_id).all()
        events = db.query(ColdDeliveryEvent).filter_by(operation_id=operation_id).all()
        return state.current_state, state.revision, reservations, events
    finally:
        db.close()


def assert_no_reservation(factory, operation_id, before):
    current, revision, reservations, events = persisted(factory, operation_id)
    assert (current, revision) == before and not reservations and not events


def durable_snapshot(factory, operation_id):
    db = factory()
    try:
        state = db.get(ColdDeliveryOperationState, operation_id)
        return {
            "state": (state.current_state, state.revision, state.next_event_sequence),
            "reservations": [(x.id, x.reservation_id, x.idempotency_key) for x in db.query(ColdDispatchReservation).filter_by(operation_id=operation_id)],
            "events": [(x.id, x.sequence_number, x.event_fingerprint) for x in db.query(ColdDeliveryEvent).filter_by(operation_id=operation_id)],
            "decisions": [(x.id, x.authority_fingerprint) for x in db.query(ColdT3Decision).filter_by(operation_id=operation_id)],
        }
    finally:
        db.close()


def test_q01_valid_dispatch_planned_reserves_once(factory):
    operation_id, authority = ready_for_reservation(factory)
    before = persisted(factory, operation_id)
    result = reserve(factory, operation_id, authority)
    current, revision, reservations, events = persisted(factory, operation_id)
    assert result["state"] == current == "DISPATCHING" and result["reused"] is False
    assert revision == before[1] + 1 and len(reservations) == 1
    reservation = reservations[0]
    assert reservation.operation_id == operation_id
    assert (reservation.execution_id, reservation.execution_fence_identity) == (str(authority.execution_id), "m9c2b4a-worker:1")
    assert [event.event_type for event in events] == ["T3_ALLOWED", "DISPATCH_RESERVED"]


def test_q02_wrong_operation_state_writes_nothing(factory):
    operation_id, authority = ready_for_reservation(factory, plan=False)
    before = durable_snapshot(factory, operation_id)
    with pytest.raises(OutreachError): reserve(factory, operation_id, authority)
    assert durable_snapshot(factory, operation_id) == before


def test_q03_missing_execution_authority_writes_nothing(factory):
    operation_id, _ = ready_for_reservation(factory); before = durable_snapshot(factory, operation_id)
    with pytest.raises(Exception): reserve(factory, operation_id, None)
    assert durable_snapshot(factory, operation_id) == before


@pytest.mark.parametrize("variant", ["execution", "owner", "generation"])
def test_q04_wrong_execution_authority_writes_nothing(factory, variant):
    operation_id, authority = ready_for_reservation(factory); before = durable_snapshot(factory, operation_id)
    wrong = {
        "execution": ExecutionLeaseAuthority(authority.execution_id + 999999, authority.lease_owner, authority.lease_generation),
        "owner": ExecutionLeaseAuthority(authority.execution_id, "wrong-owner", authority.lease_generation),
        "generation": ExecutionLeaseAuthority(authority.execution_id, authority.lease_owner, authority.lease_generation + 1),
    }[variant]
    with pytest.raises(Exception): reserve(factory, operation_id, wrong)
    assert durable_snapshot(factory, operation_id) == before


def test_q05_expired_execution_authority_writes_nothing(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        db.get(Execution, authority.execution_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    finally: db.close()
    before = durable_snapshot(factory, operation_id)
    with pytest.raises(Exception): reserve(factory, operation_id, authority)
    assert durable_snapshot(factory, operation_id) == before


def test_q06_current_suppression_blocks(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        SuppressionService(db).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc) - timedelta(seconds=1), "m9c2b4a", uuid4().hex)); db.commit()
    finally: db.close()
    result = reserve(factory, operation_id, authority)
    current, _, reservations, events = persisted(factory, operation_id)
    assert result["state"] == current == "PRE_SEND_BLOCKED" and not reservations
    assert events[-1].event_type == "PRE_SEND_BLOCKED"


def test_q07_current_permission_denial_blocks(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        PermissionService(db).append(operation.contact_point_id, PermissionEventInput("EMAIL", operation.purpose_key, "OPTED_OUT", datetime.now(timezone.utc) - timedelta(seconds=1), "m9c2b4a", uuid4().hex)); db.commit()
    finally: db.close()
    assert reserve(factory, operation_id, authority)["state"] == "PRE_SEND_BLOCKED"
    assert not persisted(factory, operation_id)[2]


def test_q08_current_contact_point_denial_blocks(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        ContactPointService(db).append_state_event(operation.contact_point_id, ContactPointStateEventInput("INVALID", "UNVERIFIED", datetime.now(timezone.utc) - timedelta(seconds=1), "m9c2b4a", uuid4().hex)); db.commit()
    finally: db.close()
    assert reserve(factory, operation_id, authority)["state"] == "PRE_SEND_BLOCKED"
    assert not persisted(factory, operation_id)[2]


def test_q09_content_commitment_mismatch_blocks(factory):
    # The operation is immutable; construct a mismatched authorization/content
    # graph at birth rather than attempting an illegal UPDATE.
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        authorization = db.get(__import__("app.models.cold_prospecting", fromlist=["ColdProspectingAuthorization"]).ColdProspectingAuthorization, operation.cold_authorization_id)
        fields = {c.name: getattr(authorization, c.name) for c in authorization.__table__.columns if c.name not in {"id", "recorded_at"}}
        fields.update(source_namespace="m9c2b4a-q09", source_event_key=sha256_fingerprint({"q09": uuid4().hex}))
        clone = authorization.__class__(**fields); db.add(clone); db.flush()
        replacement = ColdDeliveryOperation(cold_authorization_id=clone.id, lead_id=operation.lead_id, contact_point_id=operation.contact_point_id, action=operation.action, purpose_key=operation.purpose_key, purpose_family=operation.purpose_family, source_namespace="m9c2b4a-q09", source_event_key=sha256_fingerprint({"operation": uuid4().hex}), message_content_fingerprint="a" * 64, operation_schema_version="v1")
        db.add(replacement); db.flush()
        db.add(ColdDeliveryOperationState(operation_id=replacement.id, current_state="READY", revision=1, next_event_sequence=1, active_execution_id=str(authority.execution_id), active_fence_identity="m9c2b4a-worker:1")); db.commit()
        operation_id = replacement.id
        result = ColdDeliveryT3Service(db).evaluate_and_plan(operation_id, authority)
        assert result["state"] == "T3_BLOCKED"
        db.commit()
    finally: db.close()
    before = durable_snapshot(factory, operation_id)
    with pytest.raises(OutreachError): reserve(factory, operation_id, authority)
    assert durable_snapshot(factory, operation_id) == before


def test_q15_rejects_provider_without_declared_native_idempotency(factory):
    """Q15: every listed approval declaration is mandatory, not decorative."""
    operation_id, authority = ready_for_reservation(factory)
    # This is a TEST-ONLY approval.  It intentionally lacks one declaration
    # that the qualification contract says is required.
    incomplete = ColdProviderApproval("test-only", "test-v1", native_idempotency="MISSING")
    db = factory()
    try:
        before = db.get(ColdDeliveryOperationState, operation_id)
        before_revision, before_cursor = before.revision, before.next_event_sequence
        result = ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((incomplete,))).reserve(operation_id, authority)
        state = db.get(ColdDeliveryOperationState, operation_id)
        reservations = db.query(ColdDispatchReservation).filter_by(operation_id=operation_id).all()
        events = db.query(ColdDeliveryEvent).filter_by(operation_id=operation_id).order_by(ColdDeliveryEvent.sequence_number).all()
        assert result == {"operation_id": operation_id, "state": "PRE_SEND_BLOCKED", "reason_codes": ["COLD_PROVIDER_NOT_APPROVED"]}
        assert (state.current_state, state.revision, state.next_event_sequence) == ("PRE_SEND_BLOCKED", before_revision + 1, before_cursor + 1)
        assert not reservations
        assert [event.event_type for event in events] == ["T3_ALLOWED", "PRE_SEND_BLOCKED"]
        assert events[-1].safe_payload == {"reason_codes": ["COLD_PROVIDER_NOT_APPROVED"]}
    finally:
        db.close()


@pytest.mark.parametrize("field,value", [
    ("native_idempotency", None), ("native_idempotency", ""),
    ("native_idempotency", "MISSING"), ("native_idempotency", "UNKNOWN"),
    ("native_idempotency", "UNSUPPORTED"),
    ("provider_reference_support", False), ("reconciliation_lookup", False),
    ("retention_semantics", "UNSUPPORTED"),
    ("sender_domain_readiness", "UNKNOWN"),
    ("suppression_bounce_complaint_capability", "MISSING"),
])
def test_q15_incomplete_capability_declarations_fail_closed(field, value):
    approval = ColdProviderApproval("test-only", "test-v1", **{field: value})
    with pytest.raises(OutreachError) as raised:
        ColdProviderApprovalRegistry((approval,)).select()
    assert raised.value.category == "COLD_PROVIDER_NOT_APPROVED"


@pytest.mark.parametrize("kwargs", [
    {"channel": "SMS"}, {"commercial_class": "CONSENTED"}, {"approval_state": "PENDING"},
])
def test_q14_invalid_core_provider_declarations_are_rejected(kwargs):
    with pytest.raises(OutreachError) as raised:
        ColdProviderApproval("test-only", "test-v1", **kwargs)
    assert raised.value.category == "COLD_PROVIDER_NOT_APPROVED"


@pytest.mark.parametrize("key,version", [("", "test-v1"), ("test-only", "")])
def test_q15_empty_provider_identity_is_rejected(key, version):
    with pytest.raises(OutreachError):
        ColdProviderApproval(key, version)


def test_q14_resend_is_never_a_cold_provider():
    with pytest.raises(OutreachError) as raised:
        ColdProviderApprovalRegistry((ColdProviderApproval("resend", "test-v1"),)).select()
    assert raised.value.category == "COLD_PROVIDER_NOT_APPROVED"


def test_q15_complete_test_only_approval_is_selectable():
    approval = ColdProviderApproval("test-only", "test-v1")
    assert ColdProviderApprovalRegistry((approval,)).select() is approval


def test_q10_snapshot_bound_authority_ignores_newer_unrelated_records(factory):
    """M9C2A/B4A pins authority; it deliberately has no latest-record selector."""
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        auth = db.get(__import__("app.models.cold_prospecting", fromlist=["ColdProspectingAuthorization"]).ColdProspectingAuthorization, operation.cold_authorization_id)
        baseline = (auth.organization_evidence_id, auth.policy_selection_id, tuple(auth.evidence["provenance_ids"]), auth.policy_profile_key)
        registration = ColdProspectingAuthorityRegistrationService(db)
        org, _ = registration.register_organization_evidence(lead_id=operation.lead_id, source_namespace="m9c2b4a-q10", source_event_key=sha256_fingerprint({"org": uuid4().hex}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="1" * 64, evidence_fingerprint="2" * 64, evaluated_at=datetime.now(timezone.utc))
        policy, _ = registration.register_policy_selection(lead_id=operation.lead_id, source_namespace="m9c2b4a-q10", source_event_key=sha256_fingerprint({"policy": uuid4().hex}), evidence_fingerprint="3" * 64, profile_key="cold-b2b-default-v1", evaluated_at=datetime.now(timezone.utc))
        point = db.get(__import__("app.models.crm", fromlist=["ContactPoint"]).ContactPoint, operation.contact_point_id)
        ContactPointService(db).attach_provenance(point.id, ContactPointProvenanceInput("PUBLIC_BUSINESS_SOURCE", "m9c2b4a-q10", uuid4().hex, datetime.now(timezone.utc), datetime.now(timezone.utc), evidence_fingerprint="4" * 64))
        db.commit(); db.expire_all(); auth = db.get(auth.__class__, auth.id)
        assert org.id != auth.organization_evidence_id and policy.id != auth.policy_selection_id
        assert (auth.organization_evidence_id, auth.policy_selection_id, tuple(auth.evidence["provenance_ids"]), auth.policy_profile_key) == baseline
        assert ColdDeliveryT3Service(db)._binding(operation, auth)[0] is True
    finally:
        db.close()
    assert reserve(factory, operation_id, authority)["state"] == "DISPATCHING"


def test_q11_late_recipient_resolution_failure_blocks_without_reservation(factory, monkeypatch):
    operation_id, authority = ready_for_reservation(factory)
    calls = []
    def fail(**kwargs): calls.append(kwargs); raise OutreachError("RECIPIENT_RESOLUTION_FAILED", "raw@example.invalid")
    monkeypatch.setattr("app.services.cold_delivery_pre_send_service.ColdRecipientResolutionService.resolve_email", fail)
    assert reserve(factory, operation_id, authority)["state"] == "PRE_SEND_BLOCKED"
    current, _, reservations, events = persisted(factory, operation_id)
    assert calls and current == "PRE_SEND_BLOCKED" and not reservations and events[-1].safe_payload == {"reason_codes": ["RECIPIENT_RESOLUTION_FAILED"]}


def test_q12_changed_recipient_fingerprint_blocks(factory, monkeypatch):
    operation_id, authority = ready_for_reservation(factory)
    class Changed:
        def fingerprint(self): return "a" * 64
    monkeypatch.setattr("app.services.cold_delivery_pre_send_service.ColdRecipientResolutionService.resolve_email", lambda **kwargs: Changed())
    assert reserve(factory, operation_id, authority)["state"] == "PRE_SEND_BLOCKED"
    assert not persisted(factory, operation_id)[2]


def test_q13_unchanged_recipient_fingerprint_reserves(factory):
    operation_id, authority = ready_for_reservation(factory)
    assert reserve(factory, operation_id, authority)["state"] == "DISPATCHING"


def test_q16_two_postgresql_sessions_create_one_reservation(factory):
    import threading
    operation_id, authority = ready_for_reservation(factory)
    left, right = factory(), factory()
    try:
        pids = {left.execute(text("select pg_backend_pid()")).scalar_one(), right.execute(text("select pg_backend_pid()")).scalar_one()}
    finally: left.close(); right.close()
    assert len(pids) == 2
    barrier, results, errors = threading.Barrier(3), [], []
    def worker():
        db = factory()
        try: barrier.wait(15); results.append(ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority))
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    a, b = threading.Thread(target=worker), threading.Thread(target=worker); a.start(); b.start(); barrier.wait(15); a.join(30); b.join(30)
    current, _, reservations, events = persisted(factory, operation_id)
    # The serialized second caller is a legitimate DISPATCHING re-entry, not
    # a second reservation winner.
    assert not a.is_alive() and not b.is_alive() and len(results) == 2 and not errors
    assert sum(result["reused"] is False for result in results) == 1 and sum(result["reused"] is True for result in results) == 1
    assert current == "DISPATCHING" and len(reservations) == 1 and [x.event_type for x in events].count("DISPATCH_RESERVED") == 1


def test_q17_stale_state_revision_cas_writes_nothing(factory, monkeypatch):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    before = durable_snapshot(factory, operation_id)
    original = db.execute; injected = []
    def stale_cas(statement, *args, **kwargs):
        if "UPDATE cold_delivery_operation_state" in str(statement) and not injected:
            injected.append(True)
            original(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == operation_id).values(revision=3))
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(db, "execute", stale_cas)
    try:
        with pytest.raises(OutreachError): ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority)
    finally: db.rollback(); db.close()
    assert durable_snapshot(factory, operation_id) == before


def test_q18_superseded_fence_writes_nothing(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try: db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == operation_id).values(active_fence_identity="successor:2")); db.commit()
    finally: db.close()
    before = durable_snapshot(factory, operation_id)
    with pytest.raises(OutreachError): reserve(factory, operation_id, authority)
    assert durable_snapshot(factory, operation_id) == before


@pytest.mark.parametrize("point", ("reservation", "event", "commit"))
def test_q19_failure_injection_rolls_back_every_write(factory, monkeypatch, point):
    operation_id, authority = ready_for_reservation(factory); db = factory(); before = durable_snapshot(factory, operation_id)
    try:
        service = ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),)))
        if point == "reservation":
            original = db.flush; monkeypatch.setattr(db, "flush", lambda: (_ for _ in ()).throw(RuntimeError("inject")))
        elif point == "event":
            original = db.add; monkeypatch.setattr(db, "add", lambda value: (_ for _ in ()).throw(RuntimeError("inject")) if isinstance(value, ColdDeliveryEvent) else original(value))
        else: monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("inject")))
        with pytest.raises(RuntimeError): service.reserve(operation_id, authority)
    finally: db.rollback(); db.close()
    assert durable_snapshot(factory, operation_id) == before


def test_q20_committed_suppression_is_reread_before_reservation(factory):
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        SuppressionService(db).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc), "m9c2b4a-q20", uuid4().hex)); db.commit()
    finally: db.close()
    result = reserve(factory, operation_id, authority)
    assert result["state"] == "PRE_SEND_BLOCKED" and not persisted(factory, operation_id)[2]


def test_q21_suppression_writer_uses_same_fact_lock_protocol(factory):
    operation_id, _ = ready_for_reservation(factory)
    db = factory()
    try:
        operation = db.get(ColdDeliveryOperation, operation_id)
        from app.crm.cold_fact_lock import acquire_cold_fact_lock
        assert ColdDeliveryPreSendService.fact_lock_key(operation.lead_id, operation.contact_point_id, operation.purpose_key)
        acquire_cold_fact_lock(db, operation.lead_id, operation.contact_point_id, operation.purpose_key)
        # The normal writer path invokes lock_affected_cold_operations before
        # appending its immutable suppression fact.
        db.rollback()
    finally: db.close()


def test_q22_dispatching_reentry_reuses_reservation(factory):
    operation_id, authority = ready_for_reservation(factory); first = reserve(factory, operation_id, authority); second = reserve(factory, operation_id, authority)
    assert second == {"operation_id": operation_id, "state": "DISPATCHING", "reservation_id": first["reservation_id"], "reused": True}
    assert len(persisted(factory, operation_id)[2]) == 1


def test_q23_q24_durable_artifacts_exclude_raw_recipient_and_secret(factory):
    raw_recipient_marker, provider_secret_marker = "m9c2b4a-distinctive-", "M9C2B4A_FAKE_PROVIDER_SECRET"
    class MarkerBearingApprovalRegistry(ColdProviderApprovalRegistry):
        """The real select() boundary consumes this test-side configuration."""
        def __init__(self): super().__init__((valid_provider(),)); self.provider_secret_marker = provider_secret_marker
        def select(self): assert self.provider_secret_marker == provider_secret_marker; return super().select()
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try: ColdDeliveryPreSendService(db, MarkerBearingApprovalRegistry()).reserve(operation_id, authority)
    finally: db.close()
    db = factory()
    try:
        import json
        from sqlalchemy.inspection import inspect
        rows = db.query(ColdDispatchReservation).filter_by(operation_id=operation_id).all() + db.query(ColdDeliveryEvent).filter_by(operation_id=operation_id).all()
        durable = json.dumps([{column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs} for row in rows], sort_keys=True, default=str)
        assert raw_recipient_marker not in durable and provider_secret_marker not in durable
    finally: db.close()


def test_q25_single_alembic_head_includes_cursor_repair():
    from alembic.script import ScriptDirectory
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == ["f2e3d4c5b6a7"]


def test_q25_real_f2_cursor_repair_roundtrip(factory):
    """Real e1 -> f2 -> e1 -> f2 proof; the finalizer always restores f2."""
    from alembic.script import ScriptDirectory
    config, parent, repair = Config("alembic.ini"), "e1f2a3b4c5d6", "f2e3d4c5b6a7"
    db = factory()
    try:
        assert db.execute(text("select current_database()")).scalar_one() == "etm_g5_m9c2b4a_qualification"
        assert db.execute(text("select version_num from alembic_version")).scalar_one() == repair
    finally: db.close()
    try:
        command.downgrade(config, parent)
        db = factory()
        try:
            assert db.execute(text("select version_num from alembic_version")).scalar_one() == parent
        finally: db.close()
        stale_id, stale_authority = ready_for_reservation(factory)
        ahead_id, ahead_authority = ready_for_reservation(factory)
        empty_id, _ = ready_for_reservation(factory, plan=False)
        db = factory()
        try:
            stale_event = db.query(ColdDeliveryEvent).filter_by(operation_id=stale_id).one(); ahead_event = db.query(ColdDeliveryEvent).filter_by(operation_id=ahead_id).one()
            snapshot = [(x.id, x.operation_id, x.sequence_number, x.event_type, x.occurred_at, x.source_namespace, x.source_event_key, x.event_fingerprint, x.safe_payload) for x in (stale_event, ahead_event)]
            db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == stale_id).values(next_event_sequence=stale_event.sequence_number))
            db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == ahead_id).values(next_event_sequence=ahead_event.sequence_number + 3)); db.commit()
            before = {stale_id: stale_event.sequence_number, ahead_id: ahead_event.sequence_number + 3, empty_id: db.get(ColdDeliveryOperationState, empty_id).next_event_sequence}
        finally: db.close()
        command.upgrade(config, repair)
        db = factory()
        try:
            after = {identifier: db.get(ColdDeliveryOperationState, identifier).next_event_sequence for identifier in before}
            actual = [(x.id, x.operation_id, x.sequence_number, x.event_type, x.occurred_at, x.source_namespace, x.source_event_key, x.event_fingerprint, x.safe_payload) for x in db.query(ColdDeliveryEvent).filter(ColdDeliveryEvent.operation_id.in_((stale_id, ahead_id))).order_by(ColdDeliveryEvent.operation_id).all()]
            assert after == {stale_id: before[stale_id] + 1, ahead_id: before[ahead_id], empty_id: before[empty_id]} and sorted(actual) == sorted(snapshot)
            assert db.execute(text("SELECT count(*) FROM cold_delivery_operation_state s WHERE EXISTS (SELECT 1 FROM cold_delivery_events e WHERE e.operation_id=s.operation_id GROUP BY e.operation_id HAVING s.next_event_sequence <= max(e.sequence_number))")).scalar_one() == 0
        finally: db.close()
        command.downgrade(config, parent); command.upgrade(config, repair)
        db = factory()
        try:
            assert {identifier: db.get(ColdDeliveryOperationState, identifier).next_event_sequence for identifier in before} == after
            assert db.execute(text("select version_num from alembic_version")).scalar_one() == repair
            assert ScriptDirectory.from_config(config).get_heads() == [repair]
        finally: db.close()
    finally:
        command.upgrade(config, repair)


def test_q26_reservation_has_no_provider_or_network_boundary(factory, monkeypatch):
    operation_id, authority = ready_for_reservation(factory)
    import socket, httpx
    from app.outreach.providers.resend import ResendEmailProvider
    from app.outreach.provider_registry import OutreachProviderRegistry
    from app.repositories.outreach_provider_dispatch_repository import OutreachProviderDispatchRepository
    calls = []
    def tripwire(name):
        def blocked(*args, **kwargs): calls.append(name); raise AssertionError(f"forbidden B4A boundary: {name}")
        return blocked
    monkeypatch.setattr(socket, "create_connection", tripwire("socket.create_connection"))
    monkeypatch.setattr(socket.socket, "connect", tripwire("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", tripwire("socket.connect_ex"))
    monkeypatch.setattr(httpx.Client, "request", tripwire("httpx.Client.request"))
    monkeypatch.setattr(httpx, "request", tripwire("httpx.request"))
    monkeypatch.setattr(ResendEmailProvider, "__init__", tripwire("resend.credential_access"))
    monkeypatch.setattr(ResendEmailProvider, "send", tripwire("resend.send"))
    monkeypatch.setattr(OutreachProviderRegistry, "resolve", tripwire("provider_registry.resolve"))
    monkeypatch.setattr(OutreachProviderDispatchRepository, "add_reference_or_reuse", tripwire("provider_reference.create"))
    result = reserve(factory, operation_id, authority)
    current, _, reservations, events = persisted(factory, operation_id)
    from app.models.cold_delivery import ColdProviderDispatch, ColdProviderDispatchReference
    db = factory()
    try:
        provider_artifacts = db.query(ColdProviderDispatch).filter_by(operation_id=operation_id).count() + db.query(ColdProviderDispatchReference).join(ColdProviderDispatch).filter(ColdProviderDispatch.operation_id == operation_id).count()
    finally: db.close()
    assert result["state"] == current == "DISPATCHING" and result["reservation_id"] == reservations[0].reservation_id and len(reservations) == 1 and [event.event_type for event in events].count("DISPATCH_RESERVED") == 1 and provider_artifacts == 0 and calls == []


def _wait_for_advisory_wait(factory, waiter_pid, blocker_pid):
    """Return PostgreSQL's own wait evidence; polling only observes it."""
    import time
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        observer = factory()
        try:
            row = observer.execute(text("SELECT wait_event_type, wait_event, pg_blocking_pids(:pid), EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted) FROM pg_stat_activity WHERE pid=:pid"), {"pid": waiter_pid}).one_or_none()
            if row and row[0] == "Lock" and blocker_pid in row[2] and row[3]: return row
        finally: observer.close()
        time.sleep(.05)
    raise AssertionError("PostgreSQL did not report the expected advisory-lock wait")


def test_q20_suppression_first_blocks_b4a_on_real_advisory_lock(factory, monkeypatch):
    import threading
    import app.crm.cold_fact_lock as fact_lock
    operation_id, authority = ready_for_reservation(factory)
    acquired, release, b4a_started = threading.Event(), threading.Event(), threading.Event()
    pids, outcomes, errors = {}, [], []
    real_lock = fact_lock.lock_affected_cold_operations
    def held_lock(db, *args, **kwargs):
        real_lock(db, *args, **kwargs); acquired.set(); assert release.wait(15)
    monkeypatch.setattr(fact_lock, "lock_affected_cold_operations", held_lock)
    real_b4a_lock = ColdDeliveryPreSendService._lock_facts
    def observed_b4a_lock(self, operation):
        pids["b4a"] = self.db.execute(text("select pg_backend_pid()")).scalar_one(); b4a_started.set(); return real_b4a_lock(self, operation)
    monkeypatch.setattr(ColdDeliveryPreSendService, "_lock_facts", observed_b4a_lock)
    def writer():
        db = factory()
        try:
            pids["writer"] = db.execute(text("select pg_backend_pid()")).scalar_one(); operation = db.get(ColdDeliveryOperation, operation_id)
            SuppressionService(db).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc), "q20", uuid4().hex)); db.commit()
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    def b4a():
        db = factory()
        try: outcomes.append(ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority))
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    wt = threading.Thread(target=writer); wt.start(); assert acquired.wait(15)
    bt = threading.Thread(target=b4a); bt.start(); assert b4a_started.wait(15)
    evidence = _wait_for_advisory_wait(factory, pids["b4a"], pids["writer"])
    release.set(); wt.join(30); bt.join(30)
    assert not errors and outcomes[0]["state"] == "PRE_SEND_BLOCKED" and evidence[0] == "Lock" and not persisted(factory, operation_id)[2]


def test_q21_b4a_first_blocks_suppression_on_real_advisory_lock(factory, monkeypatch):
    import threading
    operation_id, authority = ready_for_reservation(factory)
    acquired, release, writer_started = threading.Event(), threading.Event(), threading.Event()
    pids, outcomes, errors = {}, [], []
    real_lock = ColdDeliveryPreSendService._lock_facts
    def held_lock(self, operation):
        real_lock(self, operation); pids["b4a"] = self.db.execute(text("select pg_backend_pid()")).scalar_one(); acquired.set(); assert release.wait(15)
    monkeypatch.setattr(ColdDeliveryPreSendService, "_lock_facts", held_lock)
    def b4a():
        db = factory()
        try: outcomes.append(ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority))
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    def writer():
        db = factory()
        try:
            pids["writer"] = db.execute(text("select pg_backend_pid()")).scalar_one(); writer_started.set(); operation = db.get(ColdDeliveryOperation, operation_id)
            SuppressionService(db).append(operation.lead_id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", datetime.now(timezone.utc), "q21", uuid4().hex)); db.commit()
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    bt = threading.Thread(target=b4a); bt.start(); assert acquired.wait(15)
    wt = threading.Thread(target=writer); wt.start(); assert writer_started.wait(15)
    evidence = _wait_for_advisory_wait(factory, pids["writer"], pids["b4a"])
    release.set(); bt.join(30); wt.join(30)
    current, _, reservations, events = persisted(factory, operation_id)
    assert not errors and outcomes[0]["state"] == "DISPATCHING" and current == "DISPATCHING" and len(reservations) == 1 and [x.event_type for x in events].count("DISPATCH_RESERVED") == 1 and evidence[0] == "Lock"


@pytest.mark.parametrize("writer_kind", ("permission", "contact_state"))
def test_q20_writer_first_temporal_invalidations_are_revalidated(factory, monkeypatch, writer_kind):
    """Permission and contact-state writers share the production fact lock."""
    import threading
    import app.crm.cold_fact_lock as fact_lock
    operation_id, authority = ready_for_reservation(factory)
    acquired, release, started = threading.Event(), threading.Event(), threading.Event()
    pids, result, errors = {}, [], []
    real_writer_lock = fact_lock.lock_affected_cold_operations
    def held_writer_lock(db, *args, **kwargs): real_writer_lock(db, *args, **kwargs); acquired.set(); assert release.wait(15)
    monkeypatch.setattr(fact_lock, "lock_affected_cold_operations", held_writer_lock)
    real_b4a_lock = ColdDeliveryPreSendService._lock_facts
    def observed_b4a_lock(self, operation): pids["b4a"] = self.db.execute(text("select pg_backend_pid()")).scalar_one(); started.set(); return real_b4a_lock(self, operation)
    monkeypatch.setattr(ColdDeliveryPreSendService, "_lock_facts", observed_b4a_lock)
    def writer():
        db = factory()
        try:
            pids["writer"] = db.execute(text("select pg_backend_pid()")).scalar_one(); op = db.get(ColdDeliveryOperation, operation_id)
            if writer_kind == "permission": PermissionService(db).append(op.contact_point_id, PermissionEventInput("EMAIL", op.purpose_key, "OPTED_OUT", datetime.now(timezone.utc), "q20-permission", uuid4().hex))
            else: ContactPointService(db).append_state_event(op.contact_point_id, ContactPointStateEventInput("INVALID", "UNVERIFIED", datetime.now(timezone.utc), "q20-contact", uuid4().hex))
            db.commit()
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    def b4a():
        db = factory()
        try: result.append(ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority))
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    wt = threading.Thread(target=writer); wt.start(); assert acquired.wait(15)
    bt = threading.Thread(target=b4a); bt.start(); assert started.wait(15)
    evidence = _wait_for_advisory_wait(factory, pids["b4a"], pids["writer"]); release.set(); wt.join(30); bt.join(30)
    assert not errors and evidence[0] == "Lock" and result[0]["state"] == "PRE_SEND_BLOCKED" and not persisted(factory, operation_id)[2]


def test_q21_b4a_first_blocks_permission_writer_on_real_advisory_lock(factory, monkeypatch):
    import threading
    operation_id, authority = ready_for_reservation(factory)
    acquired, release, started = threading.Event(), threading.Event(), threading.Event()
    pids, result, errors = {}, [], []
    real_lock = ColdDeliveryPreSendService._lock_facts
    def held_b4a_lock(self, operation):
        real_lock(self, operation); pids["b4a"] = self.db.execute(text("select pg_backend_pid()")).scalar_one(); acquired.set(); assert release.wait(15)
    monkeypatch.setattr(ColdDeliveryPreSendService, "_lock_facts", held_b4a_lock)
    def b4a():
        db = factory()
        try: result.append(ColdDeliveryPreSendService(db, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority))
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    def writer():
        db = factory()
        try:
            pids["writer"] = db.execute(text("select pg_backend_pid()")).scalar_one(); started.set(); op = db.get(ColdDeliveryOperation, operation_id)
            PermissionService(db).append(op.contact_point_id, PermissionEventInput("EMAIL", op.purpose_key, "OPTED_OUT", datetime.now(timezone.utc), "q21-permission", uuid4().hex)); db.commit()
        except Exception as error: db.rollback(); errors.append(error)
        finally: db.close()
    bt = threading.Thread(target=b4a); bt.start(); assert acquired.wait(15)
    wt = threading.Thread(target=writer); wt.start(); assert started.wait(15)
    evidence = _wait_for_advisory_wait(factory, pids["writer"], pids["b4a"]); release.set(); bt.join(30); wt.join(30)
    current, _, reservations, events = persisted(factory, operation_id)
    assert not errors and evidence[0] == "Lock" and result[0]["state"] == current == "DISPATCHING" and len(reservations) == 1 and [x.event_type for x in events].count("DISPATCH_RESERVED") == 1


def test_q18_lease_expiring_while_waiting_cannot_reserve(factory, monkeypatch):
    import threading, time
    from app.crm.cold_fact_lock import acquire_cold_fact_lock
    operation_id, authority = ready_for_reservation(factory)
    db = factory()
    try:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=2)
        db.get(Execution, authority.execution_id).lease_expires_at = expiry; db.commit()
        op = db.get(ColdDeliveryOperation, operation_id)
    finally: db.close()
    acquired, release, started = threading.Event(), threading.Event(), threading.Event(); pids, errors = {}, []
    real_lock = ColdDeliveryPreSendService._lock_facts
    def observed(self, operation): pids["b4a"] = self.db.execute(text("select pg_backend_pid()")).scalar_one(); started.set(); return real_lock(self, operation)
    monkeypatch.setattr(ColdDeliveryPreSendService, "_lock_facts", observed)
    def blocker():
        held = factory()
        try:
            pids["blocker"] = held.execute(text("select pg_backend_pid()")).scalar_one(); acquire_cold_fact_lock(held, op.lead_id, op.contact_point_id, op.purpose_key); acquired.set(); assert release.wait(15); held.commit()
        except Exception as error: held.rollback(); errors.append(error)
        finally: held.close()
    def b4a():
        session = factory()
        try: ColdDeliveryPreSendService(session, ColdProviderApprovalRegistry((valid_provider(),))).reserve(operation_id, authority)
        except Exception as error: errors.append(error)
        finally: session.rollback(); session.close()
    lock_thread = threading.Thread(target=blocker); lock_thread.start(); assert acquired.wait(15)
    b4a_thread = threading.Thread(target=b4a); b4a_thread.start(); assert started.wait(15)
    _wait_for_advisory_wait(factory, pids["b4a"], pids["blocker"])
    observer = factory()
    try:
        while observer.execute(text("select clock_timestamp() >= :expiry"), {"expiry": expiry}).scalar_one() is False: time.sleep(.05)
    finally: observer.close()
    release.set(); lock_thread.join(30); b4a_thread.join(30)
    assert any(isinstance(error, Exception) for error in errors) and not persisted(factory, operation_id)[2]
