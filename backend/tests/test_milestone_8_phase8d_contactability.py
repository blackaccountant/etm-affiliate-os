"""Focused M8D proofs for pure, read-only CRM contactability evaluation."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect

import pytest
from sqlalchemy import event

from app.crm.contact_point_state_resolution import resolve_contact_point_state
from app.crm.contactability import aggregate_lead_contactability, evaluate_contact_point, is_channel_compatible
from app.crm.contactability_contracts import (
    ContactabilityContext,
    ContactabilityReason,
    ContactabilityState,
    ContactPointSnapshot,
    ContactPointStateEventSnapshot,
    PermissionEventSnapshot,
    ResolvedContactPointState,
    ResolvedPermission,
    ResolvedSuppression,
    SuppressionEventSnapshot,
)
from app.crm.contracts import (
    CRMError,
    ContactPointStateEventInput,
    PermissionEventInput,
    SuppressionEventInput,
)
from app.crm.permission_resolution import resolve_permission
from app.crm.suppression_resolution import resolve_suppression
from app.models.crm import ContactPoint, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.contactability_evaluation_service import ContactabilityEvaluationService
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


T0 = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
AS_OF = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _state_event(identifier, state="ACTIVE", verification="VERIFIED", *, occurred=T0, recorded=T0, point="point-1"):
    return ContactPointStateEventSnapshot(identifier, point, state, verification, occurred, recorded)


def _permission(identifier, event_type="CONSENTED", *, occurred=T0, recorded=T0, point="point-1", channel="EMAIL", purpose="marketing", jurisdiction=None):
    return PermissionEventSnapshot(identifier, point, channel, purpose, event_type, jurisdiction, occurred, recorded)


def _suppression(identifier, scope="GLOBAL_LEAD", action="APPLIED", *, effective=T0, recorded=T0, lead="lead-1", point=None, channel=None, reason="MANUAL"):
    return SuppressionEventSnapshot(identifier, lead, point, scope, channel, action, reason, effective, recorded)


def _resolved_suppression(events=(), *, point="point-1", channel="EMAIL"):
    return resolve_suppression(tuple(events), lead_id="lead-1", contact_point_id=point, channel=channel, evaluated_as_of=AS_OF)


def _point_result(*, subject="PERSON", kind="EMAIL", channel="EMAIL", state="ACTIVE", verification="VERIFIED", permission="CONSENTED", suppressions=(), point="point-1"):
    context = ContactabilityContext(channel, "marketing", AS_OF)
    contact = ContactPointSnapshot(point, "lead-1", kind)
    return evaluate_contact_point(
        subject_type=subject,
        contact_point=contact,
        context=context,
        contact_state=ResolvedContactPointState(state, verification, "state-event" if state else None),
        permission=ResolvedPermission(permission, "permission-event" if permission != "UNKNOWN" else None, None),
        suppression=_resolved_suppression(suppressions, point=point, channel=channel),
    )


def test_contact_state_empty_and_frozen_states_resolve_exactly():
    assert resolve_contact_point_state((), AS_OF) == ResolvedContactPointState(None, None, None)
    for state, verification in (
        ("ACTIVE", "UNVERIFIED"),
        ("ACTIVE", "VERIFIED"),
        ("INVALID", "VERIFIED"),
        ("RETIRED", "UNVERIFIED"),
    ):
        result = resolve_contact_point_state((_state_event(state, state, verification),), AS_OF)
        assert (result.effective_state, result.effective_verification) == (state, verification)


def test_contact_state_ordering_exact_tie_is_fail_safe_and_atomic():
    earlier = _state_event("earlier", "ACTIVE", "VERIFIED", occurred=T0)
    later = _state_event("later", "ACTIVE", "UNVERIFIED", occurred=T0 + timedelta(seconds=1))
    assert resolve_contact_point_state((later, earlier), AS_OF).winning_event_id == "later"
    tied_active = _state_event("z-active", "ACTIVE", "VERIFIED")
    tied_invalid = _state_event("a-invalid", "INVALID", "UNVERIFIED")
    tied = resolve_contact_point_state((tied_active, tied_invalid), AS_OF)
    assert tied == ResolvedContactPointState("INVALID", "UNVERIFIED", "a-invalid")


def test_contact_state_explicit_as_of_excludes_future_domain_and_recorded_events():
    valid = _state_event("valid")
    future_domain = _state_event("future-domain", "INVALID", occurred=AS_OF + timedelta(seconds=1))
    future_recorded = _state_event("future-recorded", "RETIRED", recorded=AS_OF + timedelta(seconds=1))
    assert resolve_contact_point_state((future_domain, valid, future_recorded), AS_OF).winning_event_id == "valid"


@pytest.mark.parametrize("event_type", ["UNKNOWN", "CONSENTED", "OPTED_OUT", "REVOKED"])
def test_permission_no_event_and_each_frozen_state(event_type):
    empty = resolve_permission((), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert empty.effective_permission == "UNKNOWN" and empty.winning_event_id is None
    result = resolve_permission((_permission(event_type, event_type),), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert result.effective_permission == event_type


def test_permission_chronology_allows_later_explicit_change_and_exact_tie_is_restrictive():
    consent = _permission("consent", "CONSENTED")
    opt_out = _permission("opt-out", "OPTED_OUT", occurred=T0 + timedelta(seconds=1))
    assert resolve_permission((opt_out, consent), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF).effective_permission == "OPTED_OUT"
    reconsent = _permission("reconsent", "CONSENTED", occurred=T0 + timedelta(seconds=2))
    assert resolve_permission((consent, opt_out, reconsent), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF).effective_permission == "CONSENTED"
    revoked = _permission("revoked", "REVOKED")
    tied = resolve_permission((consent, revoked), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert tied.effective_permission == "REVOKED"


def test_permission_is_exactly_channel_and_purpose_scoped_without_inheritance():
    events = (
        _permission("sms", channel="SMS"),
        _permission("other-purpose", purpose="product-updates"),
    )
    result = resolve_permission(events, contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert result.effective_permission == "UNKNOWN"


def test_permission_as_of_and_jurisdiction_are_deterministic_and_decision_neutral():
    known = _permission("known", jurisdiction="NG")
    future_domain = _permission("future-domain", "OPTED_OUT", occurred=AS_OF + timedelta(seconds=1))
    future_recorded = _permission("future-recorded", "REVOKED", recorded=AS_OF + timedelta(seconds=1))
    result = resolve_permission((future_domain, known, future_recorded), contact_point_id="point-1", channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert (result.effective_permission, result.jurisdiction_context) == ("CONSENTED", "NG")


def test_suppression_each_scope_applies_and_its_own_lift_clears_only_that_scope():
    cases = (
        ("GLOBAL_LEAD", None, None),
        ("LEAD_CHANNEL", None, "EMAIL"),
        ("CONTACT_POINT_CHANNEL", "point-1", "EMAIL"),
    )
    for scope, point, channel in cases:
        applied = _suppression(f"{scope}-apply", scope, point=point, channel=channel)
        result = _resolved_suppression((applied,))
        assert result.is_suppressed
        lifted = _suppression(f"{scope}-lift", scope, "LIFTED", point=point, channel=channel, effective=T0 + timedelta(seconds=1))
        assert not _resolved_suppression((applied, lifted)).is_suppressed


def test_suppression_unrelated_channel_and_point_are_ignored():
    unrelated = (
        _suppression("sms", "LEAD_CHANNEL", channel="SMS"),
        _suppression("other-point", "CONTACT_POINT_CHANNEL", point="point-2", channel="EMAIL"),
    )
    assert not _resolved_suppression(unrelated).is_suppressed


def test_suppression_scopes_are_independent_and_lifts_cannot_cross_cancel():
    global_applied = _suppression("global")
    point_lift = _suppression("point-lift", "CONTACT_POINT_CHANNEL", "LIFTED", point="point-1", channel="EMAIL", effective=T0 + timedelta(seconds=1))
    channel_lift = _suppression("channel-lift", "LEAD_CHANNEL", "LIFTED", channel="EMAIL", effective=T0 + timedelta(seconds=1))
    assert _resolved_suppression((global_applied, point_lift, channel_lift)).is_suppressed

    channel_applied = _suppression("channel", "LEAD_CHANNEL", point=None, channel="EMAIL")
    global_lift = _suppression("global-lift", action="LIFTED", effective=T0 + timedelta(seconds=1))
    result = _resolved_suppression((global_applied, channel_applied, global_lift))
    assert result.is_suppressed
    assert [scope.scope for scope in result.scopes if scope.is_applied] == ["LEAD_CHANNEL"]


def test_suppression_exact_tie_applied_wins_and_future_events_are_excluded():
    lifted = _suppression("z-lifted", action="LIFTED")
    applied = _suppression("a-applied")
    assert _resolved_suppression((lifted, applied)).is_suppressed
    future_effective = _suppression("future-effective", effective=AS_OF + timedelta(seconds=1))
    future_recorded = _suppression("future-recorded", recorded=AS_OF + timedelta(seconds=1))
    assert not _resolved_suppression((future_effective, future_recorded)).is_suppressed


@pytest.mark.parametrize("reason", ["BOUNCE", "COMPLAINT"])
def test_bounce_and_complaint_remain_suppression_only_blockers(reason):
    result = _resolved_suppression((_suppression(reason, reason=reason),))
    assert result.is_suppressed
    assert result.scopes[0].reason == reason


@pytest.mark.parametrize(
    "subject,kind,channel,state,verification,permission,suppressions,expected,reason",
    [
        ("ANONYMOUS", "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "ANONYMOUS_SUBJECT"),
        (None, "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "SUBJECT_UNAVAILABLE"),
        ("PERSON", "EMAIL", "EMAIL", "INVALID", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "CONTACT_POINT_INVALID"),
        ("PERSON", "EMAIL", "EMAIL", "RETIRED", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "CONTACT_POINT_RETIRED"),
        ("PERSON", "PHONE", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "CHANNEL_INCOMPATIBLE"),
        ("PERSON", "WEBSITE", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "INFORMATIONAL_CONTACT_KIND"),
        ("PERSON", "SOCIAL_PROFILE", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "NOT_CONTACTABLE", "INFORMATIONAL_CONTACT_KIND"),
        ("PERSON", "EMAIL", "EMAIL", "ACTIVE", "UNVERIFIED", "CONSENTED", (), "UNKNOWN", "CONTACT_POINT_UNVERIFIED"),
        ("PERSON", "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "UNKNOWN", (), "UNKNOWN", "PERMISSION_UNKNOWN"),
        ("PERSON", "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "CONSENTED", (), "CONTACTABLE", "CONTACTABLE_WITH_CONSENT"),
        ("PERSON", "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "OPTED_OUT", (), "NOT_CONTACTABLE", "PERMISSION_OPTED_OUT"),
        ("PERSON", "EMAIL", "EMAIL", "ACTIVE", "VERIFIED", "REVOKED", (), "NOT_CONTACTABLE", "PERMISSION_REVOKED"),
    ],
)
def test_point_contactability_truth_table(subject, kind, channel, state, verification, permission, suppressions, expected, reason):
    result = _point_result(subject=subject, kind=kind, channel=channel, state=state, verification=verification, permission=permission, suppressions=suppressions)
    assert result.state == expected and reason in result.reason_codes


def test_point_definitive_suppression_and_permission_blockers_precede_unknown_evidence():
    suppression = (_suppression("global"),)
    suppressed = _point_result(verification="UNVERIFIED", permission="UNKNOWN", suppressions=suppression)
    assert suppressed.state == "NOT_CONTACTABLE" and suppressed.reason_codes == ("SUPPRESSED_GLOBAL",)
    opted = _point_result(state=None, verification=None, permission="OPTED_OUT")
    assert opted.state == "NOT_CONTACTABLE" and opted.reason_codes == ("PERMISSION_OPTED_OUT",)


@pytest.mark.parametrize(
    "kind,channel,expected",
    [
        ("EMAIL", "EMAIL", True),
        ("PHONE", "SMS", True),
        ("PHONE", "WHATSAPP", True),
        ("TELEGRAM", "TELEGRAM", True),
        ("PHONE", "EMAIL", False),
        ("EMAIL", "SMS", False),
        ("WEBSITE", "EMAIL", False),
        ("SOCIAL_PROFILE", "TELEGRAM", False),
    ],
)
def test_exact_frozen_channel_map(kind, channel, expected):
    assert is_channel_compatible(kind, channel) is expected


def test_lead_aggregation_precedence_zero_route_and_order_independence():
    context = ContactabilityContext("EMAIL", "marketing", AS_OF)
    contactable = _point_result(point="point-b")
    unknown = _point_result(point="point-a", permission="UNKNOWN")
    blocked = _point_result(point="point-c", permission="OPTED_OUT")
    result = aggregate_lead_contactability("lead-1", context, (blocked, unknown, contactable))
    reversed_result = aggregate_lead_contactability("lead-1", context, (contactable, unknown, blocked))
    assert result == reversed_result and result.state == "CONTACTABLE"
    assert result.contactable_point_ids == ("point-b",)
    assert aggregate_lead_contactability("lead-1", context, (blocked, unknown)).state == "UNKNOWN"
    assert aggregate_lead_contactability("lead-1", context, (blocked,)).state == "NOT_CONTACTABLE"
    empty = aggregate_lead_contactability("lead-1", context, ())
    assert empty.state == "NOT_CONTACTABLE" and empty.reason_codes == ("NO_COMPATIBLE_CONTACT_POINT",)


def test_contract_rejects_blank_oversized_purpose_and_naive_as_of():
    with pytest.raises(CRMError):
        ContactabilityContext("EMAIL", " ", AS_OF)
    with pytest.raises(CRMError):
        ContactabilityContext("EMAIL", "x" * 129, AS_OF)
    with pytest.raises(CRMError):
        ContactabilityContext("EMAIL", "marketing", AS_OF.replace(tzinfo=None))
    assert ContactabilityContext("EMAIL", "marketing", AS_OF).evaluated_as_of == AS_OF


def _seed_contactable_graph(db):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contacts = ContactPointService(db)
    point = contacts.create_or_reuse(lead.id, kind="EMAIL", normalized_value="private@example.com").record
    contacts.append_state_event(point.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", T0, "m8d", "state"))
    PermissionService(db).append(point.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", T0, "m8d", "permission", jurisdiction_context="NG"))
    return lead, point


def test_real_service_point_and_lead_evaluation_is_scoped_explainable_and_pii_safe(db_session):
    lead, point = _seed_contactable_graph(db_session)
    service = ContactabilityEvaluationService(db_session)
    point_result = service.evaluate_point(lead.id, point.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    lead_result = service.evaluate_lead(lead.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF)
    assert point_result.state == lead_result.state == "CONTACTABLE"
    assert lead_result.contactable_point_ids == (point.id,)
    assert point_result.winning_state_event_id and point_result.winning_permission_event_id
    assert point_result.jurisdiction_context == "NG"
    assert "private@example.com" not in repr(point_result) + repr(lead_result)
    assert db_session.in_transaction()


def test_real_service_loads_only_exact_permission_and_applicable_suppression_scope(db_session):
    lead, point = _seed_contactable_graph(db_session)
    permissions = PermissionService(db_session)
    permissions.append(point.id, PermissionEventInput("EMAIL", "other", "OPTED_OUT", T0 + timedelta(seconds=1), "m8d", "other-purpose"))
    suppressions = SuppressionService(db_session)
    suppressions.append(lead.id, SuppressionEventInput("LEAD_CHANNEL", "APPLIED", "MANUAL", T0, "m8d", "sms-only", channel="SMS"))
    result = ContactabilityEvaluationService(db_session).evaluate_point(
        lead.id, point.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF
    )
    assert result.state == "CONTACTABLE"
    assert result.effective_permission == "CONSENTED" and not result.suppression.is_suppressed


def test_service_is_read_only_uses_caller_session_and_has_no_second_session(db_session):
    lead, _ = _seed_contactable_graph(db_session)
    db_session.commit()
    counts_before = tuple(db_session.query(model).count() for model in (
        Lead, ContactPoint, ContactPointStateEvent, PermissionEvent, SuppressionEvent
    ))

    def fail_flush(*_args, **_kwargs):
        raise AssertionError("M8D attempted a database write")

    event.listen(db_session, "before_flush", fail_flush)
    try:
        result = ContactabilityEvaluationService(db_session).evaluate_lead(
            lead.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF
        )
    finally:
        event.remove(db_session, "before_flush", fail_flush)
    counts_after = tuple(db_session.query(model).count() for model in (
        Lead, ContactPoint, ContactPointStateEvent, PermissionEvent, SuppressionEvent
    ))
    assert result.state == "CONTACTABLE" and counts_after == counts_before
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_snapshot_reads_disable_autoflush_without_mutating_caller_pending_state(db_session):
    lead, _ = _seed_contactable_graph(db_session)
    db_session.commit()
    pending = Lead(subject_id=None)
    db_session.add(pending)

    def fail_flush(*_args, **_kwargs):
        raise AssertionError("M8D triggered caller-state autoflush")

    event.listen(db_session, "before_flush", fail_flush)
    try:
        result = ContactabilityEvaluationService(db_session).evaluate_lead(
            lead.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF
        )
    finally:
        event.remove(db_session, "before_flush", fail_flush)
    assert result.state == "CONTACTABLE" and pending in db_session.new
    db_session.expunge(pending)


def test_m8d_boundaries_have_no_clock_network_provider_outreach_qualification_or_lifecycle_coupling(monkeypatch, db_session):
    def fail(*_args, **_kwargs):
        raise AssertionError("forbidden boundary accessed")

    monkeypatch.setattr("socket.create_connection", fail)
    lead, _ = _seed_contactable_graph(db_session)
    result = ContactabilityEvaluationService(db_session).evaluate_lead(
        lead.id, channel="EMAIL", purpose_key="marketing", evaluated_as_of=AS_OF
    )
    assert result.state == "CONTACTABLE"
    modules = (
        __import__("app.crm.contact_point_state_resolution", fromlist=["x"]),
        __import__("app.crm.permission_resolution", fromlist=["x"]),
        __import__("app.crm.suppression_resolution", fromlist=["x"]),
        __import__("app.crm.contactability", fromlist=["x"]),
        __import__("app.services.contactability_evaluation_service", fromlist=["x"]),
    )
    source = "\n".join(inspect.getsource(module) for module in modules)
    for forbidden in (
        "datetime.now", "utcnow", "AudienceSignal", "qualification_status",
        "LeadLifecycleState", "sessionmaker", ".commit(", ".flush(", "requests.", "httpx.",
    ):
        assert forbidden not in source
    assert "repeatable-read" in inspect.getsource(modules[-1])
    assert "contactable" not in Lead.__table__.columns
