from datetime import datetime, timedelta, timezone

import pytest

from app.audience.profile_contracts import PROFILE_RULESET_VERSION, profile_source_fingerprint
from app.audience.profile_derivation import effective_signals, profile_summary
from app.models.audience import AudienceProfile, AudienceProfileSignal, AudienceSubject
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate


BASE = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _signal(db, subject, tag, *, kind="INTENT", topic="hosting", stage="PRICING",
            observed=BASE, expires_at=None, supersedes_signal_id=None, strength=50, confidence=60):
    foundation = AudienceFoundationService(db)
    subject_id = subject.id if subject is not None else None
    observation = foundation.ingest_observation(
        research_run_id=None, subject_id=subject_id, source_namespace="m63b",
        source_type="MANUAL", external_observation_id=f"observation-{tag}",
        source_reference=tag, observed_at=observed, normalized_fact={"tag": tag},
    )
    evidence = foundation.record_evidence(
        observation_id=observation.id, source_reference=f"evidence-{tag}",
        normalized_representation={"tag": tag}, content_fingerprint=(tag * 64)[:64],
    )
    return AudienceSignalService(db).persist(SignalCandidate(
        kind, topic, topic.title(), stage if kind == "INTENT" else None,
        strength, confidence, [evidence.id], "audience-signals-v1",
        observed_purchase=kind == "PURCHASE", expires_at=expires_at,
        supersedes_signal_id=supersedes_signal_id,
    ), subject_id=subject_id)


def _subject(db, kind="PERSON"):
    return AudienceFoundationService(db).create_subject(kind)


def _derive(db, subject, as_of=BASE + timedelta(days=1)):
    return AudienceProfileService(db).derive(subject.id, effective_as_of=as_of)


def test_basic_profile_has_bounded_canonical_facts_and_exact_junctions(db_session):
    subject = _subject(db_session)
    problem = _signal(db_session, subject, "problem", kind="PROBLEM", topic="latency", observed=BASE)
    intent = _signal(db_session, subject, "intent", topic="hosting", observed=BASE + timedelta(hours=1))
    result = _derive(db_session, subject)
    profile = db_session.get(AudienceProfile, result.profile_id)
    assert result.effective_signal_ids == tuple(signal.id for signal in sorted((problem, intent), key=lambda item: (item.signal_type, item.topic_slug, item.intent_stage or "", item.observed_at.isoformat(), item.id)))
    assert profile.last_signal_observed_at == intent.observed_at
    assert set(profile.summary_json["categories"]) == {"PROBLEM", "INTENT"}
    assert all("rationale" not in fact for facts in profile.summary_json["categories"].values() for fact in facts)
    assert db_session.query(AudienceProfileSignal).filter_by(profile_id=profile.id).count() == 2
    assert result.source_fingerprint == profile_source_fingerprint(subject.id, PROFILE_RULESET_VERSION, [(signal.id, signal.extraction_key) for signal in (problem, intent)])
    repeated = _derive(db_session, subject, BASE + timedelta(days=10))
    assert repeated.profile_id == result.profile_id
    assert db_session.query(AudienceProfileSignal).filter_by(profile_id=profile.id).count() == 2
    assert db_session.get(AudienceProfile, profile.id).effective_as_of == BASE + timedelta(days=1)


def test_supersession_and_branching_keep_only_all_leaf_signals(db_session):
    subject = _subject(db_session)
    first = _signal(db_session, subject, "first")
    second = _signal(db_session, subject, "second", supersedes_signal_id=first.id)
    third = _signal(db_session, subject, "third", supersedes_signal_id=first.id)
    result = _derive(db_session, subject)
    assert set(result.effective_signal_ids) == {second.id, third.id}
    assert first.id not in result.effective_signal_ids
    assert {row[0] for row in db_session.query(AudienceProfileSignal.signal_id).filter_by(profile_id=result.profile_id)} == {second.id, third.id}
    assert first.supersedes_signal_id is None


def test_expiry_is_as_of_strict_and_never_reactivates_a_superseded_predecessor(db_session):
    subject = _subject(db_session)
    active = _signal(db_session, subject, "active", topic="active", expires_at=BASE + timedelta(days=2))
    expired = _signal(db_session, subject, "expired", topic="expired", expires_at=BASE + timedelta(days=1))
    predecessor = _signal(db_session, subject, "predecessor", topic="replacement", expires_at=BASE + timedelta(days=4))
    successor = _signal(db_session, subject, "successor", topic="replacement", expires_at=BASE + timedelta(days=1), supersedes_signal_id=predecessor.id)
    result = _derive(db_session, subject, BASE + timedelta(days=1))
    assert result.effective_signal_ids == (active.id,)
    assert expired.id not in result.effective_signal_ids
    assert successor.id not in result.effective_signal_ids
    assert predecessor.id not in result.effective_signal_ids
    assert {row[0] for row in db_session.query(AudienceProfileSignal.signal_id).filter_by(profile_id=result.profile_id)} == {active.id}


def test_zero_signal_profile_and_same_set_later_time_reuse_immutable_snapshot(db_session):
    subject = _subject(db_session)
    first = _derive(db_session, subject, BASE)
    stored = db_session.get(AudienceProfile, first.profile_id)
    second = _derive(db_session, subject, BASE + timedelta(days=30))
    assert first.profile_id == second.profile_id
    assert first.effective_signal_ids == ()
    assert stored.summary_json == {"categories": {}}
    assert stored.last_signal_observed_at is None
    assert stored.effective_as_of == BASE
    assert db_session.query(AudienceProfile).filter_by(subject_id=subject.id).count() == 1
    assert db_session.query(AudienceProfileSignal).filter_by(profile_id=stored.id).count() == 0


def test_changed_effective_sets_create_profiles_without_mutating_history(db_session):
    subject = _subject(db_session)
    first_signal = _signal(db_session, subject, "first", topic="first")
    first = _derive(db_session, subject)
    first_summary = db_session.get(AudienceProfile, first.profile_id).summary_json
    added = _signal(db_session, subject, "added", topic="added")
    second = _derive(db_session, subject)
    successor = _signal(db_session, subject, "successor", topic="first", supersedes_signal_id=first_signal.id)
    third = _derive(db_session, subject)
    expiry_subject = _subject(db_session)
    expiring = _signal(db_session, expiry_subject, "expiring", topic="expiring", expires_at=BASE + timedelta(days=3))
    before_expiry = _derive(db_session, expiry_subject, BASE + timedelta(days=2))
    after_expiry = _derive(db_session, expiry_subject, BASE + timedelta(days=3))
    assert len({first.profile_id, second.profile_id, third.profile_id}) == 3
    assert {row[0] for row in db_session.query(AudienceProfileSignal.signal_id).filter_by(profile_id=first.profile_id)} == {first_signal.id}
    assert db_session.get(AudienceProfile, first.profile_id).summary_json == first_summary
    assert set(second.effective_signal_ids) == {first_signal.id, added.id}
    assert first_signal.id not in third.effective_signal_ids and successor.id in third.effective_signal_ids
    assert expiring.id in before_expiry.effective_signal_ids and after_expiry.effective_signal_ids == ()
    assert before_expiry.profile_id != after_expiry.profile_id


def test_subject_isolation_subjectless_exclusion_anonymous_and_business_need(db_session):
    person = _subject(db_session)
    other = _subject(db_session)
    anonymous = _subject(db_session, "ANONYMOUS")
    organization = _subject(db_session, "ORGANIZATION")
    person_signal = _signal(db_session, person, "person", topic="person")
    other_signal = _signal(db_session, other, "other", topic="other")
    subjectless = _signal(db_session, None, "subjectless", topic="subjectless")
    anonymous_signal = _signal(db_session, anonymous, "anonymous", topic="anonymous")
    business_need = _signal(db_session, organization, "need", kind="BUSINESS_NEED", topic="crm", stage=None)
    assert _derive(db_session, person).effective_signal_ids == (person_signal.id,)
    assert other_signal.id != person_signal.id and subjectless.id != person_signal.id
    assert _derive(db_session, anonymous).effective_signal_ids == (anonymous_signal.id,)
    assert _derive(db_session, organization).effective_signal_ids == (business_need.id,)


def test_conflicts_and_pure_ordering_are_canonical_without_database_order_dependency(db_session):
    subject = _subject(db_session)
    later = _signal(db_session, subject, "later", topic="same", observed=BASE + timedelta(hours=2), strength=70)
    earlier = _signal(db_session, subject, "earlier", topic="same", observed=BASE + timedelta(hours=1), strength=20)
    selected = effective_signals([later, earlier], effective_as_of=BASE + timedelta(days=1))
    reverse_selected = effective_signals([earlier, later], effective_as_of=BASE + timedelta(days=1))
    assert tuple(signal.id for signal in selected) == tuple(signal.id for signal in reverse_selected)
    assert profile_summary(selected) == profile_summary(reverse_selected)
    result = _derive(db_session, subject)
    assert set(result.effective_signal_ids) == {later.id, earlier.id}
    assert "score" not in str(db_session.get(AudienceProfile, result.profile_id).summary_json).lower()


def test_atomic_rollback_leaves_no_partial_profile_or_junction(db_session, monkeypatch):
    subject = _subject(db_session)
    _signal(db_session, subject, "atomic")
    db_session.commit()
    original_add = db_session.add

    def fail_at_junction(record):
        if isinstance(record, AudienceProfileSignal):
            raise RuntimeError("test junction failure")
        return original_add(record)

    monkeypatch.setattr(db_session, "add", fail_at_junction)
    with pytest.raises(RuntimeError, match="junction failure"):
        with db_session.begin():
            _derive(db_session, subject)
    assert db_session.query(AudienceProfile).count() == 0
    assert db_session.query(AudienceProfileSignal).count() == 0


def test_unknown_subject_is_a_typed_permanent_failure(db_session):
    from app.audience.profile_derivation import AudienceProfileDerivationError

    with pytest.raises(AudienceProfileDerivationError) as error:
        AudienceProfileService(db_session).derive("missing", effective_as_of=BASE)
    assert error.value.category == "SUBJECT_NOT_FOUND"
