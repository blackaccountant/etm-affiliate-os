"""Focused deterministic and TOCTOU proofs for M9A eligibility."""

from datetime import datetime, timedelta, timezone
import inspect

import pytest

from app.crm.contactability_contracts import (
    PointContactabilityResult,
    ResolvedSuppression,
    SuppressionScopeResolution,
)
from app.crm.contracts import ContactPointStateEventInput, PermissionEventInput, SuppressionEventInput
from app.outreach.contracts import (
    OUTREACH_ELIGIBILITY_POLICY_VERSION,
    CreateOutreachIntentRequest,
    OutreachEligibilityFacts,
    OutreachEligibilityState,
    PreparedOutreachMessage,
)
from app.outreach.eligibility import evaluate_outreach_eligibility
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.outreach_intent_service import OutreachIntentService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


T1 = datetime(2030, 8, 30, 12, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)


def _point(*, state="CONTACTABLE", lead="lead-1", point="point-1", channel="EMAIL", purpose="marketing", at=T1):
    suppression = ResolvedSuppression(
        False,
        (SuppressionScopeResolution("GLOBAL_LEAD", False, None, None),),
        (),
        (),
    )
    return PointContactabilityResult(
        state, lead, point, channel, purpose, at, "ACTIVE", "VERIFIED", "CONSENTED",
        suppression, ("CONTACTABLE_WITH_CONSENT",), "state-event", "permission-event", None, True,
    )


def _facts(result, **overrides):
    values = {
        "lead_id": "lead-1", "contact_point_id": "point-1", "channel": "EMAIL",
        "purpose_key": "marketing", "contactability_result": result, "message_contract_valid": True,
    }
    values.update(overrides)
    return OutreachEligibilityFacts(**values)


def _contactable_graph(db, suffix="one"):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contact = ContactPointService(db).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value=f"m9a-{suffix}@example.com",
    ).record
    ContactPointService(db).append_state_event(
        contact.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", T1, "m9a", f"state-{suffix}"),
    )
    PermissionService(db).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", T1, "m9a", f"permission-{suffix}"),
    )
    return lead, contact


def _request(lead, contact, suffix="one", at=T1):
    return CreateOutreachIntentRequest(
        lead.id, contact.id, "EMAIL", "marketing", "m9a-test", f"intent-{suffix}",
        PreparedOutreachMessage("Prepared immutable body", "Subject", "TEXT", {"reply_mode": "none"}), at,
    )


def test_pure_policy_exact_contactable_is_deterministic_and_versioned():
    result = _point()
    first = evaluate_outreach_eligibility(_facts(result))
    second = evaluate_outreach_eligibility(_facts(result))
    assert first == second
    assert first.state == OutreachEligibilityState.ELIGIBLE.value
    assert first.policy_version == OUTREACH_ELIGIBILITY_POLICY_VERSION == "outreach-eligibility-v1"


@pytest.mark.parametrize("state", ["UNKNOWN", "NOT_CONTACTABLE"])
def test_unknown_and_not_contactable_fail_closed(state):
    result = evaluate_outreach_eligibility(_facts(_point(state=state)))
    assert result.state == OutreachEligibilityState.INELIGIBLE.value
    assert result.eligible is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("lead_id", "other-lead", "LEAD_MISMATCH"),
        ("contact_point_id", "other-point", "CONTACT_POINT_MISMATCH"),
        ("channel", "SMS", "CHANNEL_MISMATCH"),
        ("purpose_key", "other-purpose", "PURPOSE_MISMATCH"),
    ],
)
def test_exact_identity_channel_and_purpose_are_required(field, value, reason):
    result = evaluate_outreach_eligibility(_facts(_point(), **{field: value}))
    assert result.state == "INELIGIBLE"
    assert reason in result.reason_codes


def test_policy_unavailable_and_invalid_message_are_fail_closed():
    unavailable = evaluate_outreach_eligibility(_facts(None))
    invalid_message = evaluate_outreach_eligibility(_facts(_point(), message_contract_valid=False))
    assert unavailable.state == "POLICY_UNAVAILABLE"
    assert invalid_message.state == "INELIGIBLE"


def test_policy_has_no_qualification_lifecycle_audience_provider_frequency_or_legal_basis_inputs():
    source = inspect.getsource(evaluate_outreach_eligibility).lower()
    for prohibited in (
        "qualification", "lifecycle", "audiencesignal", "provider", "frequency",
        "legitimate_interest", "business_contact",
    ):
        assert prohibited not in source
    assert set(OutreachEligibilityFacts.__dataclass_fields__) == {
        "lead_id", "contact_point_id", "channel", "purpose_key",
        "contactability_result", "message_contract_valid",
    }


def test_opt_out_after_creation_blocks_execution_and_preserves_creation_evidence(db_session):
    lead, contact = _contactable_graph(db_session, "optout")
    service = OutreachIntentService(db_session)
    created = service.create_or_reuse(_request(lead, contact, "optout"))
    evidence_before = dict(created.intent.contactability_evidence)
    PermissionService(db_session).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "OPTED_OUT", T2, "m9a", "optout-later"),
    )
    execution = service.revalidate_for_execution(created.intent.id, T2)
    assert execution.state == "INELIGIBLE"
    assert execution.evaluated_as_of == T2
    assert created.intent.contactability_evidence == evidence_before
    assert evidence_before["state"] == "CONTACTABLE" and evidence_before["evaluated_as_of"] == T1.isoformat()


def test_suppression_after_creation_blocks_execution_without_provider_side_effect(db_session):
    lead, contact = _contactable_graph(db_session, "suppression")
    service = OutreachIntentService(db_session)
    created = service.create_or_reuse(_request(lead, contact, "suppression"))
    SuppressionService(db_session).append(
        lead.id,
        SuppressionEventInput(
            "CONTACT_POINT_CHANNEL", "APPLIED", "MANUAL", T2, "m9a", "suppression-later",
            contact_point_id=contact.id, channel="EMAIL",
        ),
    )
    assert service.revalidate_for_execution(created.intent.id, T2).state == "INELIGIBLE"
    assert not hasattr(service, "provider")
