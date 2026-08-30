from datetime import datetime, timezone

import pytest

from app.audience.profile_contracts import PROFILE_RULESET_VERSION, AudienceProfileContractError, profile_source_fingerprint
from app.audience.segment_contracts import AudienceSegmentContractError, AudienceSegmentDefinition, AudienceSegmentSignalPredicate, segment_definition_fingerprint
from app.models.audience import AudienceProfile, AudienceSegment, AudienceSegmentMembership, AudienceSegmentRevision
from app.repositories.audience_profile_repository import AudienceProfileRepository
from app.repositories.audience_segment_membership_repository import AudienceSegmentMembershipRepository
from app.repositories.audience_segment_repository import AudienceSegmentRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate


def _subject_and_signal(db):
    foundation = AudienceFoundationService(db)
    subject = foundation.create_subject("PERSON")
    observation = foundation.ingest_observation(research_run_id=None, subject_id=subject.id, source_namespace="m63a", source_type="MANUAL", external_observation_id=None, source_reference="observation", observed_at=datetime.now(timezone.utc), normalized_fact={"event": "pricing"})
    evidence = foundation.record_evidence(observation_id=observation.id, source_reference="evidence", normalized_representation={"event": "pricing"})
    signal = AudienceSignalService(db).persist(SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "v1"), subject_id=subject.id)
    db.commit()
    return subject, signal


def _profile(subject, signal, *, summary=None):
    fingerprint = profile_source_fingerprint(subject.id, PROFILE_RULESET_VERSION, [(signal.id, signal.extraction_key)])
    return AudienceProfile(subject_id=subject.id, profile_ruleset_version=PROFILE_RULESET_VERSION, source_fingerprint=fingerprint, effective_as_of=datetime.now(timezone.utc), last_signal_observed_at=signal.observed_at, summary_json=summary if summary is not None else {"facts": []})


def test_profile_fingerprint_is_canonical_and_rejects_duplicate_signal_ids():
    first = profile_source_fingerprint("subject", PROFILE_RULESET_VERSION, [("a", "1"), ("b", "2")])
    assert first == profile_source_fingerprint("subject", PROFILE_RULESET_VERSION, [("b", "2"), ("a", "1")])
    assert first != profile_source_fingerprint("subject", PROFILE_RULESET_VERSION, [("a", "1")])
    with pytest.raises(AudienceProfileContractError): profile_source_fingerprint("subject", PROFILE_RULESET_VERSION, [("a", "1"), ("a", "2")])


def test_segment_contract_is_typed_deterministic_and_safe():
    definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="web hosting", intent_stage="PRICING", minimum_strength=50, minimum_confidence=60, max_age_days=30),), ("PERSON",))
    assert segment_definition_fingerprint(definition) == segment_definition_fingerprint(definition)
    assert definition.to_dict()["all_of"][0]["topic"] == "web-hosting"
    with pytest.raises(AudienceSegmentContractError): AudienceSegmentSignalPredicate("INTEREST", topic="political-news")
    with pytest.raises(AudienceSegmentContractError): AudienceSegmentDefinition((AudienceSegmentSignalPredicate("BUSINESS_NEED"),), ("PERSON",))


def test_profile_segment_and_membership_are_immutable_idempotent_snapshots(db_session):
    subject, signal = _subject_and_signal(db_session)
    profiles = AudienceProfileRepository(db_session)
    profile = _profile(subject, signal)
    stored = profiles.create_or_reuse(profile, [signal.id])
    assert profiles.create_or_reuse(_profile(subject, signal), [signal.id]).id == stored.id
    with pytest.raises(ValueError): profiles.create_or_reuse(_profile(subject, signal, summary={"facts": ["conflict"]}), [signal.id])
    assert profiles.list_signal_ids(stored.id) == [signal.id]

    segments = AudienceSegmentRepository(db_session)
    segment = segments.create_segment(AudienceSegment(segment_key="hosting-intent", name="Hosting intent"))
    assert segments.create_segment(AudienceSegment(segment_key="hosting-intent", name="Hosting intent")).id == segment.id
    definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="hosting"),), ("PERSON",))
    revision = AudienceSegmentRevision(segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1", definition_fingerprint=segment_definition_fingerprint(definition), definition_json=definition.to_dict())
    saved_revision = segments.create_revision_or_reuse(revision)
    assert segments.create_revision_or_reuse(AudienceSegmentRevision(segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1", definition_fingerprint=revision.definition_fingerprint, definition_json=definition.to_dict())).id == saved_revision.id
    with pytest.raises(ValueError): segments.create_revision_or_reuse(AudienceSegmentRevision(segment_id=segment.id, revision_number=2, segment_ruleset_version="audience-segment-v1", definition_fingerprint=revision.definition_fingerprint, definition_json={"all_of": []}))

    memberships = AudienceSegmentMembershipRepository(db_session)
    yes = memberships.create_or_reuse(AudienceSegmentMembership(segment_revision_id=saved_revision.id, profile_id=stored.id, is_member=True))
    assert memberships.create_or_reuse(AudienceSegmentMembership(segment_revision_id=saved_revision.id, profile_id=stored.id, is_member=True)).id == yes.id
    with pytest.raises(ValueError): memberships.create_or_reuse(AudienceSegmentMembership(segment_revision_id=saved_revision.id, profile_id=stored.id, is_member=False))
    other = AudienceProfile(subject_id=subject.id, profile_ruleset_version="audience-profile-v2", source_fingerprint="f" * 64, effective_as_of=datetime.now(timezone.utc), last_signal_observed_at=None, summary_json={"facts": []})
    other = profiles.create_or_reuse(other, [])
    assert memberships.create_or_reuse(AudienceSegmentMembership(segment_revision_id=saved_revision.id, profile_id=other.id, is_member=False)).is_member is False


def test_new_models_have_no_scoring_contact_or_mutable_update_api():
    for model in (AudienceProfile, AudienceSegmentRevision, AudienceSegmentMembership):
        assert not any(name.startswith("update") for name in dir(model))
    fields = set(AudienceProfile.__table__.columns) | set(AudienceSegment.__table__.columns) | set(AudienceSegmentRevision.__table__.columns) | set(AudienceSegmentMembership.__table__.columns)
    assert not {"lead_score", "intent_score", "qualification_score", "consent", "email", "phone"} & {column.name for column in fields}
