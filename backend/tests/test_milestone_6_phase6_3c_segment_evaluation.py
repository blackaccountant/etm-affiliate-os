from datetime import datetime, timedelta, timezone

import pytest

from app.audience.segment_contracts import AudienceSegmentDefinition, AudienceSegmentSignalPredicate, segment_definition_fingerprint
from app.models.audience import AudienceProfile, AudienceSegment, AudienceSegmentMembership, AudienceSegmentRevision
from app.repositories.audience_segment_repository import AudienceSegmentRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_segment_membership_service import AudienceSegmentMembershipError, AudienceSegmentMembershipService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate

BASE = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def signal(db, subject, tag, *, kind="INTENT", topic="hosting", stage="PRICING", strength=50, confidence=60, observed=BASE):
    f = AudienceFoundationService(db); o = f.ingest_observation(research_run_id=None, subject_id=subject.id, source_namespace="m63c", source_type="MANUAL", external_observation_id=tag, source_reference=tag, observed_at=observed, normalized_fact={"tag": tag})
    e = f.record_evidence(observation_id=o.id, source_reference=tag, normalized_representation={"tag": tag}, content_fingerprint=(tag * 64)[:64])
    return AudienceSignalService(db).persist(SignalCandidate(kind, topic, topic.title(), stage if kind == "INTENT" else None, strength, confidence, [e.id], "v1"), subject_id=subject.id)


def profile(db, kind="PERSON", signals=()):
    subject = AudienceFoundationService(db).create_subject(kind)
    for args in signals: signal(db, subject, *args)
    return AudienceProfileService(db).derive(subject.id, effective_as_of=BASE)


def revision(db, definition, key="segment"):
    repo = AudienceSegmentRepository(db); segment = repo.create_segment(AudienceSegment(segment_key=key, name=key))
    value = AudienceSegmentRevision(segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1", definition_fingerprint=segment_definition_fingerprint(definition), definition_json=definition.to_dict())
    return repo.create_revision_or_reuse(value)


def test_true_false_reuse_subject_types_and_all_predicates(db_session):
    p = profile(db_session, signals=(("problem",), ("intent",)))
    definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="hosting", intent_stage="PRICING", minimum_strength=50, minimum_confidence=60), AudienceSegmentSignalPredicate("INTENT", topic="hosting")), ("PERSON",))
    good = revision(db_session, definition, "good")
    service = AudienceSegmentMembershipService(db_session)
    first = service.evaluate(p.profile_id, good.id); stored = db_session.get(AudienceSegmentMembership, first.membership_id)
    again = service.evaluate(p.profile_id, good.id)
    assert first.is_member is True and again.membership_id == first.membership_id and again.is_member is True
    assert db_session.get(AudienceSegmentMembership, first.membership_id).evaluated_at == stored.evaluated_at
    wrong_type = revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),), ("ORGANIZATION",)), "wrong-type")
    false = service.evaluate(p.profile_id, wrong_type.id)
    assert false.is_member is False and service.evaluate(p.profile_id, wrong_type.id).membership_id == false.membership_id


def test_exact_predicates_thresholds_recency_and_zero_profiles(db_session):
    p = profile(db_session, signals=(("fact",),))
    service = AudienceSegmentMembershipService(db_session)
    exact = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="hosting", intent_stage="PRICING", minimum_strength=50, minimum_confidence=60, max_age_days=1),))
    assert service.evaluate(p.profile_id, revision(db_session, exact, "exact").id).is_member is True
    no_match = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="host"),))
    assert service.evaluate(p.profile_id, revision(db_session, no_match, "no-match").id).is_member is False
    zero = profile(db_session)
    assert service.evaluate(zero.profile_id, revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),)), "zero").id).is_member is False


def test_integrity_rejections_and_conflicting_membership(db_session):
    p = profile(db_session, signals=(("fact",),)); definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),)); r = revision(db_session, definition, "integrity")
    db_session.commit(); service = AudienceSegmentMembershipService(db_session)
    db_session.add(AudienceSegmentMembership(segment_revision_id=r.id, profile_id=p.profile_id, is_member=False))
    db_session.commit()
    with pytest.raises(AudienceSegmentMembershipError, match="immutable result"): service.evaluate(p.profile_id, r.id)
    stored = db_session.get(AudienceProfile, p.profile_id); stored.summary_json = {"categories": {"INTENT": []}}
    with pytest.raises(AudienceSegmentMembershipError): service.evaluate(p.profile_id, r.id)
    db_session.rollback()


def test_definition_fingerprint_and_atomic_rollback(db_session, monkeypatch):
    p = profile(db_session, signals=(("fact",),)); definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),)); r = revision(db_session, definition, "fingerprint")
    db_session.commit()
    r.definition_fingerprint = "x" * 64
    with pytest.raises(AudienceSegmentMembershipError, match="fingerprint"): AudienceSegmentMembershipService(db_session).evaluate(p.profile_id, r.id)
    db_session.rollback(); r = revision(db_session, definition, "atomic")
    db_session.commit(); original = db_session.add
    def fail(record):
        if isinstance(record, AudienceSegmentMembership): raise RuntimeError("membership failure")
        return original(record)
    monkeypatch.setattr(db_session, "add", fail)
    with pytest.raises(RuntimeError):
        with db_session.begin(): AudienceSegmentMembershipService(db_session).evaluate(p.profile_id, r.id)
    assert db_session.query(AudienceSegmentMembership).count() == 0


def test_sensitive_persisted_definition_is_rejected_before_membership(db_session):
    p = profile(db_session, signals=(("fact",),))
    r = revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),)), "sensitive")
    r.definition_json = {"all_of": [{"signal_type": "INTENT", "topic": "political-news", "intent_stage": None, "minimum_strength": None, "minimum_confidence": None, "max_age_days": None}], "allowed_subject_types": []}
    with pytest.raises(AudienceSegmentMembershipError) as error:
        AudienceSegmentMembershipService(db_session).evaluate(p.profile_id, r.id)
    assert error.value.category == "MALFORMED_SEGMENT_REVISION"
    assert db_session.query(AudienceSegmentMembership).count() == 0


def test_recency_boundaries_and_later_repeat_are_snapshot_deterministic(db_session):
    subject = AudienceFoundationService(db_session).create_subject("PERSON")
    signal(db_session, subject, "boundary", observed=BASE - timedelta(days=2))
    p = AudienceProfileService(db_session).derive(subject.id, effective_as_of=BASE)
    service = AudienceSegmentMembershipService(db_session)
    boundary = revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", max_age_days=2),)), "boundary")
    outside = revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", max_age_days=1),)), "outside")
    first = service.evaluate(p.profile_id, boundary.id)
    persisted = db_session.get(AudienceSegmentMembership, first.membership_id)
    later = service.evaluate(p.profile_id, boundary.id)
    assert first.is_member is True and later.membership_id == first.membership_id
    assert later.is_member is True and db_session.get(AudienceSegmentMembership, first.membership_id).evaluated_at == persisted.evaluated_at
    assert service.evaluate(p.profile_id, outside.id).is_member is False


def test_all_predicates_are_satisfied_by_distinct_complete_facts(db_session):
    subject = AudienceFoundationService(db_session).create_subject("PERSON")
    problem = signal(db_session, subject, "problem-email", kind="PROBLEM", topic="email deliverability")
    intent = signal(db_session, subject, "intent-email", kind="INTENT", topic="email deliverability", stage="PRICING")
    p = AudienceProfileService(db_session).derive(subject.id, effective_as_of=BASE)
    definition = AudienceSegmentDefinition((
        AudienceSegmentSignalPredicate("PROBLEM", topic="email deliverability"),
        AudienceSegmentSignalPredicate("INTENT", topic="email deliverability", intent_stage="PRICING"),
    ))
    result = AudienceSegmentMembershipService(db_session).evaluate(p.profile_id, revision(db_session, definition, "distinct-facts").id)
    assert problem.signal_type != intent.signal_type
    assert result.is_member is True


def test_structurally_malformed_persisted_revision_rejects_without_membership(db_session):
    p = profile(db_session, signals=(("fact",),))
    r = revision(db_session, AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT"),)), "malformed")
    r.definition_json = {"all_of": [], "allowed_subject_types": []}
    with pytest.raises(AudienceSegmentMembershipError) as error:
        AudienceSegmentMembershipService(db_session).evaluate(p.profile_id, r.id)
    assert error.value.category == "MALFORMED_SEGMENT_REVISION"
    assert db_session.query(AudienceSegmentMembership).count() == 0
