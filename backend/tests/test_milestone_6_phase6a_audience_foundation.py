"""Focused deterministic contracts for the M6.1 audience foundation."""

from datetime import datetime, timezone

import pytest

from app.audience.contracts import AudienceSubjectType
from app.models.audience import AudienceEvidence, AudienceExternalIdentity, AudienceObservation, AudienceResearchRun, AudienceSubject
from app.services.audience_foundation_service import AudienceFoundationService


def service(db_session):
    return AudienceFoundationService(db_session)


def observation_input(**overrides):
    value = {
        "research_run_id": None,
        "subject_id": None,
        "source_namespace": "public-web",
        "source_type": "PUBLIC_WEB",
        "external_observation_id": "post-1",
        "source_reference": "https://example.test/post-1",
        "observed_at": datetime(2026, 8, 30, tzinfo=timezone.utc),
        "normalized_fact": {"event": "pricing_page_view", "count": 3},
        "metadata_json": {"adapter": "fixture"},
    }
    value.update(overrides)
    return value


def test_subject_uses_immutable_uuid_identity_and_supported_types(db_session):
    audience = service(db_session)
    records = [audience.create_subject(kind.value) for kind in AudienceSubjectType]
    assert len({record.id for record in records}) == 3
    assert {record.subject_type for record in records} == {kind.value for kind in AudienceSubjectType}
    assert all(len(record.id) == 36 for record in records)


def test_external_identity_normalizes_email_and_resolves_same_subject(db_session):
    audience = service(db_session)
    first = audience.get_or_create_subject_for_identity(
        subject_type="PERSON", source_namespace="first-party", identity_type="EMAIL",
        reference="  Member@Example.TEST ", verification_state="FIRST_PARTY_VERIFIED",
    )
    second = audience.get_or_create_subject_for_identity(
        subject_type="ORGANIZATION", source_namespace="first-party", identity_type="email",
        reference="member@example.test",
    )
    identity = db_session.query(AudienceExternalIdentity).one()
    assert first.id == second.id == identity.subject_id
    assert identity.normalized_reference == "member@example.test"


def test_external_identity_cannot_attach_to_two_subjects(db_session):
    audience = service(db_session)
    first = audience.create_subject("PERSON")
    second = audience.create_subject("PERSON")
    audience.attach_external_identity(first.id, source_namespace="public-social", identity_type="account", reference="CaseSensitive")
    with pytest.raises(ValueError, match="another audience subject"):
        audience.attach_external_identity(second.id, source_namespace="public-social", identity_type="account", reference="CaseSensitive")


def test_display_name_similarity_never_merges_subjects(db_session):
    audience = service(db_session)
    first = audience.get_or_create_subject_for_identity(
        subject_type="PERSON", source_namespace="public-social", identity_type="account", reference="alex-1",
    )
    second = audience.get_or_create_subject_for_identity(
        subject_type="PERSON", source_namespace="public-social", identity_type="account", reference="alex-2",
    )
    assert first.id != second.id


def test_research_run_is_deterministically_idempotent_and_conflicts_reject(db_session):
    audience = service(db_session)
    first = audience.get_or_create_research_run(
        scope_type="category", scope_reference="managed hosting", idempotency_key="audience-research:hosting",
        metadata_json={"language": "en"},
    )
    second = audience.get_or_create_research_run(
        scope_type="category", scope_reference="managed hosting", idempotency_key="audience-research:hosting",
        metadata_json={"language": "en"},
    )
    assert first.id == second.id
    with pytest.raises(ValueError, match="conflicts"):
        audience.get_or_create_research_run(
            scope_type="category", scope_reference="email marketing", idempotency_key="audience-research:hosting",
            metadata_json={"language": "en"},
        )


def test_observation_key_is_deterministic_and_ingestion_is_idempotent(db_session):
    audience = service(db_session)
    first = audience.ingest_observation(**observation_input())
    second = audience.ingest_observation(**observation_input())
    assert first.id == second.id and len(first.observation_key) == 64
    assert db_session.query(AudienceObservation).count() == 1


def test_subjectless_observation_and_research_link_are_supported(db_session):
    audience = service(db_session)
    run = audience.get_or_create_research_run(
        scope_type="topic", scope_reference="hosting costs", idempotency_key="audience-research:costs",
    )
    observation = audience.ingest_observation(**observation_input(research_run_id=run.id, subject_id=None))
    assert observation.research_run_id == run.id and observation.subject_id is None


def test_conflicting_duplicate_observation_is_rejected_without_mutation(db_session):
    audience = service(db_session)
    existing = audience.ingest_observation(**observation_input())
    with pytest.raises(ValueError, match="immutable source fact"):
        audience.ingest_observation(**observation_input(normalized_fact={"event": "checkout"}))
    assert db_session.get(AudienceObservation, existing.id).normalized_fact == {"event": "pricing_page_view", "count": 3}


def test_observation_without_external_id_uses_canonical_fact_fingerprint(db_session):
    audience = service(db_session)
    first = audience.ingest_observation(**observation_input(external_observation_id=None))
    second = audience.ingest_observation(**observation_input(external_observation_id=None))
    assert first.id == second.id


def test_evidence_fingerprint_is_deterministic_and_idempotent(db_session):
    audience = service(db_session)
    observation = audience.ingest_observation(**observation_input())
    first = audience.record_evidence(
        observation_id=observation.id, source_reference="post-1", source_uri="https://example.test/post-1",
        excerpt="Viewed pricing three times", normalized_representation={"text": "Viewed pricing three times"},
        content_fingerprint="a" * 64,
    )
    second = audience.record_evidence(
        observation_id=observation.id, source_reference="post-1", source_uri="https://example.test/post-1",
        excerpt="Viewed pricing three times", normalized_representation={"text": "Viewed pricing three times"},
        content_fingerprint="a" * 64,
    )
    assert first.id == second.id and len(first.evidence_fingerprint) == 64
    assert db_session.query(AudienceEvidence).count() == 1


def test_evidence_conflict_is_rejected_and_evidence_stays_linked_to_observation(db_session):
    audience = service(db_session)
    observation = audience.ingest_observation(**observation_input())
    evidence = audience.record_evidence(
        observation_id=observation.id, source_reference="post-1",
        normalized_representation={"text": "pricing interest"}, content_fingerprint="b" * 64,
    )
    with pytest.raises(ValueError, match="immutable provenance"):
        audience.record_evidence(
            observation_id=observation.id, source_reference="post-1", source_uri="https://changed.test",
            normalized_representation={"text": "pricing interest"}, content_fingerprint="b" * 64,
        )
    assert db_session.get(AudienceEvidence, evidence.id).observation_id == observation.id


def test_sensitive_targeting_fields_are_not_part_of_subject_schema():
    prohibited = {"religion", "race", "ethnicity", "political_affiliation", "health_condition", "sexual_orientation"}
    assert prohibited.isdisjoint(AudienceSubject.__table__.columns.keys())


def test_foundation_has_exactly_the_five_authorized_models():
    tables = {
        AudienceResearchRun.__tablename__, AudienceSubject.__tablename__,
        AudienceExternalIdentity.__tablename__, AudienceObservation.__tablename__,
        AudienceEvidence.__tablename__,
    }
    assert len(tables) == 5
