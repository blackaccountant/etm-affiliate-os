"""Focused M8B proofs for pure normalization and exact M8A registration."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.crm.contact_normalization import normalize_contact_point
from app.crm.contact_normalization_contracts import (
    NORMALIZATION_VERSION,
    ContactNormalizationCandidate,
    ContactNormalizationContext,
    ContactNormalizationError,
)
from app.crm.contracts import CRMError, ContactPointProvenanceInput, ContactPointStateEventInput
from app.models.audience import AudienceSubject
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_registration_service import ContactPointRegistrationService
from app.services.lead_service import LeadService


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def _candidate(kind, value, *, region=None, platform=None):
    return ContactNormalizationCandidate(
        kind,
        value,
        ContactNormalizationContext(country_region=region, social_platform=platform),
    )


def _normalize(kind, value, *, region=None, platform=None):
    return normalize_contact_point(_candidate(kind, value, region=region, platform=platform))


def _lead(db, subject_type="PERSON"):
    subject = AudienceFoundationService(db).create_subject(subject_type)
    lead = LeadService(db).create_or_reuse(subject.id).record
    return subject, lead


def _provenance(key="source-1"):
    return ContactPointProvenanceInput("USER_PROVIDED", "m8b-test", key, NOW, NOW, evidence_fingerprint="a" * 64)


def _state(key="state-1"):
    return ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW, "m8b-test", key)


def test_email_preserves_local_semantics_normalizes_domain_and_is_idempotent():
    result = _normalize("EMAIL", "  User.Name+tag@BÜCHER.Example  ")
    assert result.normalized_value == "User.Name+tag@xn--bcher-kva.example"
    assert result.normalization_version == NORMALIZATION_VERSION
    assert _normalize("EMAIL", result.normalized_value) == result
    assert _normalize("EMAIL", "user.name@example.com").normalized_value != _normalize("EMAIL", "User.Name+tag@example.com").normalized_value


@pytest.mark.parametrize("value", [
    "missing-at.example.com", "two@@example.com", ".leading@example.com",
    "double..dot@example.com", '"quoted"@example.com', "Name <user@example.com>", "user@[127.0.0.1]",
])
def test_email_rejects_malformed_or_unsupported_forms_without_pii(value):
    with pytest.raises(ContactNormalizationError) as error:
        _normalize("EMAIL", value)
    assert error.value.category in {"INVALID_CONTACT_VALUE", "UNSUPPORTED_CONTACT_FORMAT"}
    assert value not in str(error.value)


def test_phone_international_national_context_and_idempotency():
    international = _normalize("PHONE", "+1 (415) 555-2671")
    national = _normalize("PHONE", "(415) 555-2671", region="us")
    assert international.normalized_value == national.normalized_value == "+14155552671"
    assert _normalize("PHONE", international.normalized_value) == international


def test_phone_requires_context_and_rejects_invalid_or_ambiguous_input():
    with pytest.raises(ContactNormalizationError) as missing:
        _normalize("PHONE", "020 7183 8750")
    assert missing.value.category == "MISSING_COUNTRY_CONTEXT"
    with pytest.raises(ContactNormalizationError) as invalid:
        _normalize("PHONE", "123", region="US")
    assert invalid.value.category == "INVALID_CONTACT_VALUE"
    with pytest.raises(ContactNormalizationError) as ambiguous:
        _normalize("PHONE", "+1 415 555 2671 / +44 20 7183 8750")
    assert ambiguous.value.category == "AMBIGUOUS_CONTACT_VALUE"


def test_telegram_supported_forms_converge_case_insensitively_and_are_idempotent():
    values = (
        "@Example_User", "example_user", "https://t.me/EXAMPLE_USER",
        "https://telegram.me/example_user/",
    )
    assert {_normalize("TELEGRAM", value).normalized_value for value in values} == {"example_user"}
    result = _normalize("TELEGRAM", values[0])
    assert _normalize("TELEGRAM", result.normalized_value) == result


@pytest.mark.parametrize("value", [
    "https://t.me/+invite", "https://t.me/joinchat/token", "https://t.me/example_user/12",
    "https://t.me/example_user?start=token", "https://t.me/example_user#fragment", "https://t.me/c/123/4",
    "https://t.me:bad/example_user",
])
def test_telegram_rejects_invite_deep_link_message_and_query_forms(value):
    with pytest.raises(ContactNormalizationError):
        _normalize("TELEGRAM", value)


def test_website_canonicalizes_only_safe_components_and_is_idempotent():
    result = _normalize("WEBSITE", "HTTPS://BÜCHER.Example:443/a/%7e/B?b=2&a=1&a=3#fragment")
    assert result.normalized_value == "https://xn--bcher-kva.example/a/%7E/B?b=2&a=1&a=3"
    assert _normalize("WEBSITE", result.normalized_value) == result
    assert _normalize("WEBSITE", "http://Example.com:8080/path").normalized_value == "http://example.com:8080/path"


def test_website_preserves_scheme_path_query_and_trailing_slash_semantics():
    assert _normalize("WEBSITE", "http://example.com").normalized_value != _normalize("WEBSITE", "https://example.com").normalized_value
    assert _normalize("WEBSITE", "https://example.com").normalized_value != _normalize("WEBSITE", "https://example.com/").normalized_value
    assert _normalize("WEBSITE", "https://example.com/a/../b").normalized_value.endswith("/a/../b")
    assert _normalize("WEBSITE", "https://example.com/?x=1&x=2&y=3").normalized_value.endswith("/?x=1&x=2&y=3")


@pytest.mark.parametrize("value", [
    "example.com", "ftp://example.com", "https://user:secret@example.com",
    "https://example.com:bad/", "https://example.com:/", "https://example.com/%ZZ",
])
def test_website_rejects_missing_scheme_credentials_invalid_port_and_bad_escapes(value):
    with pytest.raises(ContactNormalizationError) as error:
        _normalize("WEBSITE", value)
    assert value not in str(error.value)


def test_linkedin_person_company_url_and_canonical_forms_converge():
    person = _normalize("SOCIAL_PROFILE", "https://www.linkedin.com/in/Alice-Smith/")
    assert person.normalized_value == "linkedin:in/Alice-Smith"
    assert _normalize("SOCIAL_PROFILE", "linkedin:in/Alice-Smith") == person
    company = _normalize("SOCIAL_PROFILE", "company/Example-Co", platform="linkedin")
    assert company.normalized_value == "linkedin:company/Example-Co"
    assert _normalize("SOCIAL_PROFILE", company.normalized_value) == company


def test_youtube_handle_channel_url_and_canonical_forms_remain_distinct():
    handle = _normalize("SOCIAL_PROFILE", "https://www.youtube.com/@Creator.One")
    assert handle.normalized_value == "youtube:handle/creator.one"
    assert _normalize("SOCIAL_PROFILE", "@CREATOR.ONE", platform="youtube") == handle
    channel = _normalize("SOCIAL_PROFILE", "https://youtube.com/channel/UC1234567890AbCdEfGhIjKl")
    assert channel.normalized_value == "youtube:channel/UC1234567890AbCdEfGhIjKl"
    assert _normalize("SOCIAL_PROFILE", channel.normalized_value) == channel
    assert handle.normalized_value != channel.normalized_value


def test_social_profiles_reject_unsupported_ambiguous_and_non_profile_forms():
    with pytest.raises(ContactNormalizationError) as platform:
        ContactNormalizationContext(social_platform="instagram")
    assert platform.value.category == "UNSUPPORTED_SOCIAL_PLATFORM"
    with pytest.raises(ContactNormalizationError) as canonical_platform:
        _normalize("SOCIAL_PROFILE", "instagram:alice")
    assert canonical_platform.value.category == "UNSUPPORTED_SOCIAL_PLATFORM"
    for value in ("Some Display Name", "https://youtube.com/watch?v=abc", "https://youtu.be/abc", "https://linkedin.com/search/results/people"):
        with pytest.raises(ContactNormalizationError):
            _normalize("SOCIAL_PROFILE", value, platform="youtube" if "://" not in value else None)


@pytest.mark.parametrize("first,second", [
    ("Person@EXAMPLE.com", "Person@example.com"),
    ("Person@example.com", "Person@EXAMPLE.com"),
])
def test_registration_uses_frozen_m8a_and_reuses_equivalent_forms_in_both_orders(db_session, first, second):
    _, lead = _lead(db_session)
    service = ContactPointRegistrationService(db_session)
    initial = service.register(lead.id, _candidate("EMAIL", first), _provenance(), _state())
    repeated = service.register(lead.id, _candidate("EMAIL", second), _provenance(), _state())
    assert repeated.contact_point_id == initial.contact_point_id
    assert initial.reused is False and repeated.reused is True
    assert repeated.provenance_reused is True and repeated.state_event_reused is True
    stored = db_session.get(ContactPoint, initial.contact_point_id)
    assert stored.normalized_value == "Person@example.com"
    assert "normalization_version" not in ContactPoint.__table__.columns
    assert db_session.query(ContactPointProvenance).filter_by(contact_point_id=stored.id).count() == 1
    assert db_session.query(ContactPointStateEvent).filter_by(contact_point_id=stored.id).count() == 1
    assert db_session.in_transaction()


def test_cross_owner_conflict_propagates_without_merge_or_pii(db_session):
    first_subject, first_lead = _lead(db_session)
    second_subject, second_lead = _lead(db_session, "ORGANIZATION")
    service = ContactPointRegistrationService(db_session)
    service.register(first_lead.id, _candidate("EMAIL", "private@EXAMPLE.com"), _provenance("first"))
    with pytest.raises(CRMError) as error:
        service.register(second_lead.id, _candidate("EMAIL", "private@example.com"), _provenance("second"))
    assert error.value.category == "CONTACT_POINT_OWNERSHIP_CONFLICT"
    assert "private@example.com" not in str(error.value)
    assert db_session.query(Lead).count() == 2
    assert db_session.query(AudienceSubject).count() == 2
    assert {first_subject.id, second_subject.id} == {first_lead.subject_id, second_lead.subject_id}


def test_website_and_social_registration_remain_informational(db_session):
    _, lead = _lead(db_session, "ORGANIZATION")
    service = ContactPointRegistrationService(db_session)
    website = service.register(lead.id, _candidate("WEBSITE", "https://Example.com"), _provenance("website"))
    social = service.register(lead.id, _candidate("SOCIAL_PROFILE", "linkedin:company/Example"), _provenance("social"))
    assert {db_session.get(ContactPoint, value.contact_point_id).kind for value in (website, social)} == {"WEBSITE", "SOCIAL_PROFILE"}
    assert db_session.query(PermissionEvent).count() == 0
    assert db_session.query(SuppressionEvent).count() == 0


def test_normalization_and_registration_do_not_use_network(monkeypatch, db_session):
    def fail(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr("socket.create_connection", fail)
    _, lead = _lead(db_session)
    result = ContactPointRegistrationService(db_session).register(
        lead.id, _candidate("WEBSITE", "https://example.com/path"), _provenance("offline")
    )
    assert result.contact_point_id


def test_registration_graph_is_caller_owned_and_fully_rolls_back(db_session, db_session_factory):
    subject, lead = _lead(db_session)
    subject_id, lead_id = subject.id, lead.id
    db_session.commit()
    db_session.execute(text("BEGIN"))
    result = ContactPointRegistrationService(db_session).register(
        lead_id,
        _candidate("PHONE", "(415) 555-2671", region="US"),
        _provenance("rollback-provenance"),
        _state("rollback-state"),
    )
    assert db_session.in_transaction()
    assert db_session.get(ContactPoint, result.contact_point_id) is not None
    assert db_session.query(ContactPointProvenance).filter_by(contact_point_id=result.contact_point_id).count() == 1
    assert db_session.query(ContactPointStateEvent).filter_by(contact_point_id=result.contact_point_id).count() == 1
    db_session.rollback()
    verifier = db_session_factory()
    try:
        assert verifier.query(ContactPoint).count() == 0
        assert verifier.query(ContactPointProvenance).count() == 0
        assert verifier.query(ContactPointStateEvent).count() == 0
        assert verifier.query(Lead).filter_by(id=lead_id).count() == 1
        assert verifier.query(AudienceSubject).filter_by(id=subject_id).count() == 1
    finally:
        verifier.close()


def test_candidate_repr_and_normalization_errors_do_not_expose_raw_pii():
    raw = "Very.Secret+tag@example.com"
    candidate = _candidate("EMAIL", raw)
    assert raw not in repr(candidate)
    malformed = "secret value that is not an email"
    with pytest.raises(ContactNormalizationError) as error:
        _normalize("EMAIL", malformed)
    assert malformed not in str(error.value)
