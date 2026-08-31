"""T3, fencing, immutable events, replay, expiry, drift, and privacy proofs."""

from datetime import datetime, timedelta, timezone

import pytest

from app.crm.contracts import (
    ContactPointProvenanceInput,
    ContactPointStateEventInput,
    PermissionEventInput,
    SuppressionEventInput,
)
from app.models.execution import Execution
from app.models.outreach import OutreachMessage
from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.models.outreach_provider_dispatch import OutreachProviderDispatch, OutreachProviderReference
from app.outreach.contracts import CreateOutreachIntentRequest, OutreachEligibilityResult, PreparedOutreachMessage
from app.outreach.delivery_contracts import PrepareDeliveryAttemptRequest
from app.outreach.provider_contracts import (
    ProviderCapabilities, ProviderFailure, ProviderFailureCategory, ProviderSendOutcome, ProviderSendResult,
)
from app.outreach.provider_registry import OutreachProviderRegistry
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_runtime_context import ExecutionRuntimeContext, activate_execution_runtime_context
from app.services.lead_service import LeadService
from app.services.outreach_delivery_attempt_service import OutreachDeliveryAttemptService
from app.services.outreach_intent_service import OutreachIntentService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService
from app.workflows.outreach_delivery_workflow import OutreachDeliveryWorkflow


T1 = datetime(2035, 1, 1, 12, tzinfo=timezone.utc)


class FakeProvider:
    capabilities = ProviderCapabilities("resend", "resend-email-v1", ("EMAIL",), True, timedelta(hours=24), timedelta(hours=23), True)
    def __init__(self, results, sender="ETM <sender@example.com>"):
        self.results = list(results); self.sender_identity = sender; self.calls = []; self.side_effects = set()
    def send(self, request):
        self.calls.append(request)
        result = self.results.pop(0) if self.results else ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque-id")
        if result.outcome is ProviderSendOutcome.DEFINITELY_ACCEPTED:
            self.side_effects.add((request.operation_key, request.provider_payload_fingerprint))
        return result


def setup_delivery(db, suffix="one"):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contact = ContactPointService(db).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value=f"m9c-{suffix}@example.com",
    ).record
    ContactPointService(db).append_state_event(contact.id, ContactPointStateEventInput(
        "ACTIVE", "VERIFIED", T1, "m9c", f"state-{suffix}",
    ))
    PermissionService(db).append(contact.id, PermissionEventInput(
        "EMAIL", "marketing", "CONSENTED", T1, "m9c", f"permission-{suffix}",
    ))
    created = OutreachIntentService(db).create_or_reuse(CreateOutreachIntentRequest(
        lead.id, contact.id, "EMAIL", "marketing", "m9c-intent", f"intent-{suffix}",
        PreparedOutreachMessage("Immutable body", "Immutable subject", "TEXT"), T1,
    ))
    prepared = OutreachDeliveryAttemptService(db).prepare_initial(PrepareDeliveryAttemptRequest(
        created.intent.id, "m9c-prepare", suffix, T1,
    ))
    execution = ExecutionRepository(db).create("outreach_delivery", commit=False)
    authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
    assert ExecutionRepository(db).acquire_lease(authority, 3600, commit=False)
    db.commit()
    return lead, contact, created, prepared, authority


def run(factory, provider, attempt_id, authority, at=T1 + timedelta(minutes=1)):
    registry = OutreachProviderRegistry(); registry.register("resend", lambda: provider)
    workflow = OutreachDeliveryWorkflow(factory, registry, clock=lambda: at)
    with activate_execution_runtime_context(ExecutionRuntimeContext(authority, "mission")):
        return workflow.execute({"delivery_attempt_id": attempt_id})


def test_eligible_t3_accepts_once_with_started_before_call_and_persists_only_safe_facts(db_session, db_session_factory):
    _, contact, _, prepared, authority = setup_delivery(db_session, "accepted")
    provider = FakeProvider([ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque-email-id")])
    result = run(db_session_factory, provider, prepared.attempt.id, authority)
    db_session.expire_all()
    types = [event.event_type for event in db_session.query(OutreachDeliveryEvent).filter_by(delivery_attempt_id=prepared.attempt.id).order_by(OutreachDeliveryEvent.sequence_number)]
    assert result.success and result.data["outcome"] == "PROVIDER_ACCEPTED"
    assert types == ["PREPARED", "DISPATCH_PLANNED", "DISPATCH_STARTED", "PROVIDER_ACCEPTED"]
    assert len(provider.calls) == 1 and db_session.query(OutreachProviderDispatch).count() == 1
    assert db_session.query(OutreachProviderReference).one().provider_reference == "opaque-email-id"
    persisted = repr(db_session.query(OutreachProviderDispatch).one().__dict__) + repr([event.safe_payload for event in db_session.query(OutreachDeliveryEvent)])
    assert contact.normalized_value not in persisted and "Immutable body" not in persisted


def test_terminal_reentry_never_reauthorizes_or_calls_provider(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "reentry")
    provider = FakeProvider([ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque")])
    first = run(db_session_factory, provider, prepared.attempt.id, authority)
    second = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=2))
    assert first.success and second.success and second.data["outcome"] == "PROVIDER_ACCEPTED"
    assert len(provider.calls) == 1 and db_session.query(OutreachDeliveryAttempt).count() == 1


@pytest.mark.parametrize("block", ["optout", "suppression"])
def test_t3_change_after_prepared_blocks_provider_with_no_cold_bypass(db_session, db_session_factory, block):
    lead, contact, _, prepared, authority = setup_delivery(db_session, block)
    if block == "optout":
        PermissionService(db_session).append(contact.id, PermissionEventInput(
            "EMAIL", "marketing", "OPTED_OUT", T1 + timedelta(minutes=1), "m9c", "later-optout",
        ))
    else:
        SuppressionService(db_session).append(lead.id, SuppressionEventInput(
            "CONTACT_POINT_CHANNEL", "APPLIED", "MANUAL", T1 + timedelta(minutes=1), "m9c", "later-suppression",
            contact_point_id=contact.id, channel="EMAIL",
        ))
    db_session.commit()
    provider = FakeProvider([])
    result = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(minutes=2))
    assert result.success and result.data["outcome"] == "AUTHORIZATION_BLOCKED"
    assert provider.calls == [] and db_session.query(OutreachProviderDispatch).count() == 0


def test_public_enriched_business_cold_prospect_context_cannot_bypass_unknown_permission(
    db_session, db_session_factory,
):
    _, contact, _, prepared, authority = setup_delivery(db_session, "explicit-cold-boundary")
    provenance = ContactPointService(db_session).attach_provenance(
        contact.id,
        ContactPointProvenanceInput(
            "PUBLIC_BUSINESS_SOURCE",
            "enrichment",
            "public-business-email",
            observed_at=T1,
            captured_at=T1,
            evidence_reference="test-labels:cold,business,prospect,enriched",
        ),
    ).record
    PermissionService(db_session).append(contact.id, PermissionEventInput(
        "EMAIL", "marketing", "UNKNOWN", T1 + timedelta(minutes=1),
        "m9c", "public-enriched-cold-permission-unknown",
        jurisdiction_context="business-prospect",
    ))
    db_session.commit()
    provider = FakeProvider([])
    result = run(
        db_session_factory, provider, prepared.attempt.id, authority,
        T1 + timedelta(minutes=2),
    )
    assert provenance.source_type == "PUBLIC_BUSINESS_SOURCE"
    assert provenance.source_namespace == "enrichment"
    assert provenance.evidence_reference == "test-labels:cold,business,prospect,enriched"
    assert result.success and result.data["outcome"] == "AUTHORIZATION_BLOCKED"
    assert provider.calls == []
    assert db_session.query(OutreachProviderDispatch).count() == 0


def test_stale_execution_cannot_call_or_write_outcome(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "stale")
    db_session.get(Execution, authority.execution_id).lease_generation += 1; db_session.commit()
    provider = FakeProvider([])
    with pytest.raises(ExecutionLeaseLostError):
        run(db_session_factory, provider, prepared.attempt.id, authority)
    assert provider.calls == [] and db_session.query(OutreachProviderDispatch).count() == 0
    assert db_session.query(OutreachDeliveryEvent).count() == 1


def test_safe_transient_retries_same_operation_and_payload_inside_23_hours(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "transient")
    deferred = ProviderSendResult(None, failure=ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "RATE_LIMIT"))
    provider = FakeProvider([deferred, ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque")])
    first = run(db_session_factory, provider, prepared.attempt.id, authority)
    second = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=22, minutes=59))
    assert not first.success and first.data["outcome"] == "DISPATCH_DEFERRED"
    assert second.success and second.data["outcome"] == "PROVIDER_ACCEPTED"
    assert len(provider.calls) == 2
    assert provider.calls[0].operation_key == provider.calls[1].operation_key
    assert provider.calls[0].provider_payload_fingerprint == provider.calls[1].provider_payload_fingerprint
    assert db_session.query(OutreachProviderDispatch).count() == db_session.query(OutreachDeliveryAttempt).count() == 1


def test_unresolved_at_exactly_23_hours_becomes_ambiguous_without_call(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "expiry")
    deferred = ProviderSendResult(None, failure=ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "RATE_LIMIT"))
    provider = FakeProvider([deferred])
    run(db_session_factory, provider, prepared.attempt.id, authority)
    result = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=23, minutes=1))
    assert result.success and result.data["outcome"] == "PROVIDER_AMBIGUOUS"
    assert result.data["safe_message"] == "provider result requires reconciliation" and len(provider.calls) == 1


@pytest.mark.parametrize("drift", ["sender", "recipient", "message"])
def test_configuration_and_payload_drift_fail_closed_with_same_key(db_session, db_session_factory, drift):
    _, contact, created, prepared, authority = setup_delivery(db_session, f"drift-{drift}")
    deferred = ProviderSendResult(None, failure=ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "RATE_LIMIT"))
    first_provider = FakeProvider([deferred])
    run(db_session_factory, first_provider, prepared.attempt.id, authority)
    if drift == "recipient": contact.normalized_value = f"changed-{drift}@example.com"
    if drift == "message": created.message.body = "Changed immutable body"
    db_session.commit()
    second_provider = FakeProvider([], sender="Changed <changed@example.com>" if drift == "sender" else first_provider.sender_identity)
    result = run(db_session_factory, second_provider, prepared.attempt.id, authority, T1 + timedelta(hours=1))
    assert result.success is False and second_provider.calls == []
    assert "drift" in result.errors[0].lower()
    assert db_session.query(OutreachProviderDispatch).count() == 1


def test_ambiguous_result_is_terminal_business_success_and_never_auto_replayed(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "ambiguous")
    ambiguous = ProviderSendResult(
        ProviderSendOutcome.AMBIGUOUS,
        failure=ProviderFailure(ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, "AMBIGUOUS"),
    )
    provider = FakeProvider([ambiguous])
    first = run(db_session_factory, provider, prepared.attempt.id, authority)
    second = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=1))
    assert first.success and second.success and first.data["outcome"] == second.data["outcome"] == "PROVIDER_AMBIGUOUS"
    assert len(provider.calls) == 1


def test_deterministic_rejection_is_terminal_and_never_replayed(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "rejected")
    rejected = ProviderSendResult(
        ProviderSendOutcome.DEFINITELY_REJECTED,
        failure=ProviderFailure(ProviderFailureCategory.DETERMINISTIC_REJECTION, "REJECTED"),
    )
    provider = FakeProvider([rejected])
    first = run(db_session_factory, provider, prepared.attempt.id, authority)
    second = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=1))
    assert first.success and second.success
    assert first.data["outcome"] == second.data["outcome"] == "PROVIDER_REJECTED"
    assert len(provider.calls) == 1 and db_session.query(OutreachDeliveryAttempt).count() == 1


def test_missing_prepared_and_policy_unavailable_make_zero_provider_calls(monkeypatch, db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "missing-prepared")
    db_session.delete(db_session.query(OutreachDeliveryEvent).filter_by(
        delivery_attempt_id=prepared.attempt.id, sequence_number=1,
    ).one()); db_session.commit()
    provider = FakeProvider([])
    missing = run(db_session_factory, provider, prepared.attempt.id, authority)
    assert missing.success is False and "prepared" in missing.errors[0].lower() and provider.calls == []

    _, _, _, prepared_two, authority_two = setup_delivery(db_session, "policy-unavailable")
    unavailable = OutreachEligibilityResult(
        "POLICY_UNAVAILABLE", ("CONTACTABILITY_UNAVAILABLE",), "outreach-eligibility-v1",
        "a" * 64, T1, None,
    )
    monkeypatch.setattr(
        "app.services.outreach_provider_delivery_service.OutreachIntentService.revalidate_for_execution",
        lambda *_args, **_kwargs: unavailable,
    )
    blocked = run(db_session_factory, provider, prepared_two.attempt.id, authority_two)
    assert blocked.success and blocked.data["outcome"] == "AUTHORIZATION_BLOCKED" and provider.calls == []


def test_provider_call_has_no_open_workflow_database_transaction(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "outside-transaction")
    sessions = []
    def factory():
        session = db_session_factory(); sessions.append(session); return session
    class TransactionInspectingProvider(FakeProvider):
        def send(self, request):
            assert sessions[-1].in_transaction() is False
            return super().send(request)
    provider = TransactionInspectingProvider([
        ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque"),
    ])
    result = run(factory, provider, prepared.attempt.id, authority)
    assert result.success and len(sessions) == 1


def test_provider_accept_then_local_crash_replays_same_key_and_has_one_logical_side_effect(monkeypatch, db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "crash-after-accept")
    provider = FakeProvider([
        ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque"),
        ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque"),
    ])
    from app.repositories.outreach_provider_dispatch_repository import OutreachProviderDispatchRepository
    original = OutreachProviderDispatchRepository.add_reference_or_reuse
    failures = [True]
    def crash_once(self, proposed):
        if failures:
            failures.pop()
            raise RuntimeError("simulated local persistence crash")
        return original(self, proposed)
    monkeypatch.setattr(OutreachProviderDispatchRepository, "add_reference_or_reuse", crash_once)
    with pytest.raises(RuntimeError, match="simulated local persistence crash"):
        run(db_session_factory, provider, prepared.attempt.id, authority)
    recovered = run(db_session_factory, provider, prepared.attempt.id, authority, T1 + timedelta(hours=1))
    assert recovered.success and recovered.data["outcome"] == "PROVIDER_ACCEPTED"
    assert len(provider.calls) == 2 and len(provider.side_effects) == 1
    assert provider.calls[0].operation_key == provider.calls[1].operation_key
    assert provider.calls[0].provider_payload_fingerprint == provider.calls[1].provider_payload_fingerprint
    assert db_session.query(OutreachDeliveryAttempt).count() == db_session.query(OutreachProviderDispatch).count() == 1


def test_authority_lost_during_provider_call_prevents_outcome_write(db_session, db_session_factory):
    _, _, _, prepared, authority = setup_delivery(db_session, "post-call-fence")
    class LeaseStealingProvider(FakeProvider):
        def send(self, request):
            other = db_session_factory()
            try:
                execution = other.get(Execution, authority.execution_id)
                execution.lease_generation += 1
                other.commit()
            finally:
                other.close()
            return super().send(request)
    provider = LeaseStealingProvider([ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque")])
    with pytest.raises(ExecutionLeaseLostError):
        run(db_session_factory, provider, prepared.attempt.id, authority)
    db_session.expire_all()
    types = {event.event_type for event in db_session.query(OutreachDeliveryEvent).filter_by(delivery_attempt_id=prepared.attempt.id)}
    assert len(provider.calls) == 1 and "DISPATCH_STARTED" in types and "PROVIDER_ACCEPTED" not in types
    assert db_session.query(OutreachProviderReference).count() == 0
