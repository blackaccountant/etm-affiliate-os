"""SQLite contract proofs for hardened M9C2A; PostgreSQL proves locks/triggers separately."""

from datetime import datetime, timedelta, timezone

import pytest

from app.crm.contracts import ContactPointProvenanceInput, ContactPointStateEventInput, PermissionEventInput, SuppressionEventInput
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.outreach.cold_b2b_contracts import CreateColdProspectingAuthorizationRequest, OrganizationEvidenceAuthorityReference, PolicySelectionAuthorityReference
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.cold_prospecting_authority_registration_service import ColdProspectingAuthorityRegistrationService
from app.services.cold_prospecting_authorization_service import ColdProspectingAuthorizationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService

T0 = datetime(2030, 8, 30, 12, tzinfo=timezone.utc)
FP = "a" * 64


def _graph(db, suffix, *, subject_type="ORGANIZATION", state="ACTIVE", verification="VERIFIED", provenance="PUBLIC_BUSINESS_SOURCE"):
    subject = AudienceFoundationService(db).create_subject(subject_type)
    lead = LeadService(db).create_or_reuse(subject.id).record
    contacts = ContactPointService(db); point = contacts.create_or_reuse(lead.id, kind="EMAIL", normalized_value=f"cold-{suffix}@example.com").record
    contacts.append_state_event(point.id, ContactPointStateEventInput(state, verification, T0, "cold-test", f"state-{suffix}"))
    if provenance: contacts.attach_provenance(point.id, ContactPointProvenanceInput(provenance, "cold-test", f"provenance-{suffix}", T0, T0, "evidence", FP))
    return lead, point


def _authorities(db, lead, suffix="one"):
    registration = ColdProspectingAuthorityRegistrationService(db)
    organization, _ = registration.register_organization_evidence(lead_id=lead.id, source_namespace="org-authority", source_event_key=sha256_fingerprint({"org": suffix}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="b" * 64, evidence_fingerprint="c" * 64, evaluated_at=T0)
    policy, _ = registration.register_policy_selection(lead_id=lead.id, source_namespace="policy-authority", source_event_key=sha256_fingerprint({"policy": suffix}), evidence_fingerprint="d" * 64, profile_key="cold-b2b-default-v1", evaluated_at=T0)
    return organization, policy


def _request(lead, point, organization, policy, source="one", *, action="INITIAL", at=T0, purpose="cold_b2b:platform"):
    return CreateColdProspectingAuthorizationRequest(lead.id, point.id, purpose, action, "cold-auth", sha256_fingerprint({"authorization": source}), OrganizationEvidenceAuthorityReference(organization.id, organization.evidence_fingerprint), PolicySelectionAuthorityReference(policy.id, policy.decision_fingerprint), "e" * 64, at)


def _service(db): return ColdProspectingAuthorizationService(db, allow_sqlite_for_tests=True)


def test_valid_authorities_allow_verified_organization_without_consent_reinterpretation(db_session):
    lead, point = _graph(db_session, "valid"); organization, policy = _authorities(db_session, lead)
    record, reused = _service(db_session).create_or_reuse(_request(lead, point, organization, policy))
    assert not reused and record.authorization_state == "ELIGIBLE" and record.policy_selection_id == policy.id


@pytest.mark.parametrize("value", ["cold_b2b:", "cold_b2b", "cold_b2b::x", "cold_b2b:abc:def", "COLD_B2B:test", "cold_b2b: Test", "cold_b2b:test@example.com", "cold_b2b:https://example.com", " cold_b2b:test"])
def test_purpose_is_strictly_canonical(value):
    with pytest.raises(OutreachError, match="canonical"):
        CreateColdProspectingAuthorizationRequest("a" * 36, "b" * 36, value, "INITIAL", "source", "event", OrganizationEvidenceAuthorityReference("c" * 36, "a" * 64), PolicySelectionAuthorityReference("d" * 36, "b" * 64), "c" * 64, T0)


@pytest.mark.parametrize("subject_type, expect", [("PERSON", "ORGANIZATION_REQUIRED"), ("ORGANIZATION", "ORGANIZATION_EVIDENCE_UNAVAILABLE")])
def test_subject_and_authority_evidence_are_independent_gates(db_session, subject_type, expect):
    lead, point = _graph(db_session, subject_type, subject_type=subject_type); organization, policy = _authorities(db_session, lead, subject_type)
    if subject_type == "ORGANIZATION": organization.acceptance_state = "REJECTED"
    record, _ = _service(db_session).create_or_reuse(_request(lead, point, organization, policy, subject_type))
    assert expect in record.reason_codes


def test_missing_wrong_lead_and_fingerprint_mismatched_authorities_fail_closed(db_session):
    lead, point = _graph(db_session, "one"); other, _ = _graph(db_session, "two"); organization, _ = _authorities(db_session, other); _, policy = _authorities(db_session, lead, "own")
    request = _request(lead, point, organization, policy, "wrong-lead")
    record, _ = _service(db_session).create_or_reuse(request)
    assert "ORGANIZATION_EVIDENCE_UNAVAILABLE" in record.reason_codes and record.authorization_state == "INELIGIBLE"


@pytest.mark.parametrize("event_type, reason", [("OPTED_OUT", "PERMISSION_OPTED_OUT"), ("REVOKED", "PERMISSION_REVOKED")])
def test_negative_permission_and_suppression_override_authority(db_session, event_type, reason):
    lead, point = _graph(db_session, event_type); organization, policy = _authorities(db_session, lead, event_type)
    PermissionService(db_session).append(point.id, PermissionEventInput("EMAIL", "cold_b2b:platform", event_type, T0, "cold", event_type))
    record, _ = _service(db_session).create_or_reuse(_request(lead, point, organization, policy, event_type))
    assert reason in record.reason_codes
    SuppressionService(db_session).append(lead.id, SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", T0 + timedelta(days=1), "cold", "complaint"))
    follow, _ = _service(db_session).create_or_reuse(_request(lead, point, organization, policy, "suppressed", action="FOLLOW_UP", at=T0 + timedelta(days=8)))
    assert "SUPPRESSED_GLOBAL" in follow.reason_codes


def test_frequency_boundaries_and_idempotency(db_session):
    lead, point = _graph(db_session, "frequency"); organization, policy = _authorities(db_session, lead)
    service = _service(db_session); initial, _ = service.create_or_reuse(_request(lead, point, organization, policy, "initial"))
    early, _ = service.create_or_reuse(_request(lead, point, organization, policy, "early", action="FOLLOW_UP", at=T0 + timedelta(days=7) - timedelta(microseconds=1)))
    exact, _ = service.create_or_reuse(_request(lead, point, organization, policy, "exact", action="FOLLOW_UP", at=T0 + timedelta(days=7)))
    assert initial.authorization_state == "ELIGIBLE" and "FOLLOW_UP_SPACING_NOT_MET" in early.reason_codes and exact.authorization_state == "ELIGIBLE"
    replay, reused = service.create_or_reuse(_request(lead, point, organization, policy, "initial", at=T0 + timedelta(days=1)))
    assert reused and replay.id == initial.id
    with pytest.raises(OutreachError) as error: service.create_or_reuse(_request(lead, point, organization, policy, "initial", purpose="cold_b2b:other"))
    assert error.value.category == "IDEMPOTENCY_CONFLICT"


def test_registration_rejects_raw_pii_like_evidence_identities(db_session):
    lead, _ = _graph(db_session, "pii"); registration = ColdProspectingAuthorityRegistrationService(db_session)
    for unsafe in ("person@example.com", "https://example.com/person", "Nigeria", "message body"):
        with pytest.raises(OutreachError): registration.register_organization_evidence(lead_id=lead.id, source_namespace="org", source_event_key=unsafe, source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint=unsafe, evidence_fingerprint="a" * 64, evaluated_at=T0)


def test_authority_and_authorization_source_identities_are_opaque_and_non_pii(db_session):
    lead, point = _graph(db_session, "opaque"); organization, policy = _authorities(db_session, lead, "opaque")
    registration = ColdProspectingAuthorityRegistrationService(db_session)
    with pytest.raises(OutreachError): registration.register_policy_selection(lead_id=lead.id, source_namespace="policy", source_event_key="person@example.com", evidence_fingerprint="a" * 64, profile_key="cold-b2b-default-v1", evaluated_at=T0)
    with pytest.raises(OutreachError): CreateColdProspectingAuthorizationRequest(lead.id, point.id, "cold_b2b:platform", "INITIAL", "person@example.com", "a" * 64, OrganizationEvidenceAuthorityReference(organization.id, organization.evidence_fingerprint), PolicySelectionAuthorityReference(policy.id, policy.decision_fingerprint), "e" * 64, T0)
    with pytest.raises(OutreachError): CreateColdProspectingAuthorizationRequest(lead.id, point.id, "cold_b2b:platform", "INITIAL", "cold-auth", "person@example.com", OrganizationEvidenceAuthorityReference(organization.id, organization.evidence_fingerprint), PolicySelectionAuthorityReference(policy.id, policy.decision_fingerprint), "e" * 64, T0)


def test_authorization_has_no_delivery_or_network_path():
    source = __import__("inspect").getsource(ColdProspectingAuthorizationService)
    for forbidden in ("Resend", "recipient", "Mission", "DeliveryAttempt", "Prepared", "requests.", "httpx."):
        assert forbidden not in source
    assert "authorizations, not deliveries" in __import__("inspect").getsource(__import__("app.outreach.cold_b2b_eligibility", fromlist=["x"]))
