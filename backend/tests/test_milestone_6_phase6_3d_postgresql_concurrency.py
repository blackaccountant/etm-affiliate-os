"""Guarded G5 proof for immutable M6.3 profile and membership convergence."""

import os
import threading
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.audience.segment_contracts import (
    AudienceSegmentDefinition,
    AudienceSegmentSignalPredicate,
    segment_definition_fingerprint,
)
from app.models.audience import AudienceProfile, AudienceSegment, AudienceSegmentMembership, AudienceSegmentRevision
from app.repositories.audience_profile_repository import AudienceProfileRepository
from app.repositories.audience_segment_membership_repository import AudienceSegmentMembershipRepository
from app.repositories.audience_segment_repository import AudienceSegmentRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_segment_membership_service import AudienceSegmentMembershipService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate


REVISION = "c7d3e4f5a6b7"
AS_OF = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (
    _url.drivername.startswith("postgresql")
    and _url.host == "127.0.0.1"
    and _url.port == 5432
    and _url.database == "etm_affiliate_os_g5_test"
):
    raise RuntimeError("G5 only")


@pytest.fixture(scope="module")
def engine():
    result = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    try:
        with result.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == REVISION
        yield result
    finally:
        result.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_signal(db, subject_id, token):
    foundation = AudienceFoundationService(db)
    observation = foundation.ingest_observation(
        research_run_id=None, subject_id=subject_id, source_namespace="m63d-race",
        source_type="MANUAL", external_observation_id=token, source_reference=f"observation:{token}",
        observed_at=AS_OF, normalized_fact={"token": token},
    )
    evidence = foundation.record_evidence(
        observation_id=observation.id, source_reference=f"evidence:{token}",
        normalized_representation={"token": token}, content_fingerprint=(token * 64)[:64],
    )
    signal = AudienceSignalService(db).persist(
        SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "v1"),
        subject_id=subject_id,
    )
    return observation.id, evidence.id, signal.id


def _seed_profile(factory):
    db = factory()
    token = uuid4().hex
    try:
        subject = AudienceFoundationService(db).create_subject("PERSON")
        observation_id, evidence_id, signal_id = _seed_signal(db, subject.id, token)
        db.commit()
        return {
            "token": token, "subject_id": subject.id, "observation_id": observation_id,
            "evidence_id": evidence_id, "signal_id": signal_id,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cleanup(engine, state):
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM audience_segment_memberships WHERE profile_id IN (SELECT id FROM audience_profiles WHERE subject_id = :subject_id)"), state)
        connection.execute(text("DELETE FROM audience_segment_revisions WHERE segment_id IN (SELECT id FROM audience_segments WHERE segment_key = :segment_key)"), {**state, "segment_key": f"m63d-{state['token']}"})
        connection.execute(text("DELETE FROM audience_segments WHERE segment_key = :segment_key"), {**state, "segment_key": f"m63d-{state['token']}"})
        connection.execute(text("DELETE FROM audience_profile_signals WHERE profile_id IN (SELECT id FROM audience_profiles WHERE subject_id = :subject_id)"), state)
        connection.execute(text("DELETE FROM audience_profiles WHERE subject_id = :subject_id"), state)
        connection.execute(text("DELETE FROM audience_signal_evidence WHERE signal_id = :signal_id"), state)
        connection.execute(text("DELETE FROM audience_signals WHERE id = :signal_id"), state)
        connection.execute(text("DELETE FROM audience_evidence WHERE id = :evidence_id"), state)
        connection.execute(text("DELETE FROM audience_observations WHERE id = :observation_id"), state)
        connection.execute(text("DELETE FROM audience_subjects WHERE id = :subject_id"), state)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audience_profiles WHERE subject_id = :subject_id"), state).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM audience_subjects WHERE id = :subject_id"), state).scalar_one() == 0


def _run_two_callers(factory, call):
    ready, results, errors, pids = threading.Barrier(3), [], [], []
    result_lock = threading.Lock()

    def contender():
        db = factory()
        try:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with result_lock:
                pids.append(pid)
            ready.wait(timeout=10)
            result = call(db)
            assert db.in_transaction()
            db.commit()
            with result_lock:
                results.append(result)
        except Exception as error:
            db.rollback()
            with result_lock:
                errors.append(error)
        finally:
            db.close()

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.wait(timeout=10)
    for thread in threads:
        thread.join(20)
    assert all(not thread.is_alive() for thread in threads)
    assert len(pids) == 2 and pids[0] != pids[1]
    assert errors == []
    assert not any(isinstance(error, IntegrityError) for error in errors)
    return results


def test_postgresql_concurrent_identical_profile_derivation_converges(factory, engine, monkeypatch):
    state = _seed_profile(factory)
    gate = threading.Barrier(2)
    original = AudienceProfileRepository.create_or_reuse

    def synchronized_create_or_reuse(self, *args, **kwargs):
        gate.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AudienceProfileRepository, "create_or_reuse", synchronized_create_or_reuse)
    try:
        results = _run_two_callers(
            factory,
            lambda db: AudienceProfileService(db).derive(state["subject_id"], effective_as_of=AS_OF),
        )
        assert len(results) == 2
        assert len({result.profile_id for result in results}) == 1
        assert len({result.source_fingerprint for result in results}) == 1
        verifier = factory()
        try:
            identity = results[0]
            profiles = verifier.query(AudienceProfile).filter_by(
                subject_id=state["subject_id"], profile_ruleset_version=identity.profile_ruleset_version,
                source_fingerprint=identity.source_fingerprint,
            ).all()
            assert len(profiles) == 1
            junctions = AudienceProfileRepository(verifier).list_signal_ids(profiles[0].id)
            assert junctions == [state["signal_id"]]
            assert len(junctions) == len(set(junctions))
            assert profiles[0].summary_json["categories"]["INTENT"][0]["signal_id"] == state["signal_id"]
            assert verifier.execute(text("SELECT count(*) FROM audience_signals WHERE id = :signal_id"), state).scalar_one() == 1
        finally:
            verifier.close()
    finally:
        _cleanup(engine, state)


def test_postgresql_concurrent_identical_membership_evaluation_converges(factory, engine, monkeypatch):
    state = _seed_profile(factory)
    setup = factory()
    try:
        profile = AudienceProfileService(setup).derive(state["subject_id"], effective_as_of=AS_OF)
        definition = AudienceSegmentDefinition((AudienceSegmentSignalPredicate("INTENT", topic="hosting", intent_stage="PRICING"),), ("PERSON",))
        segment = AudienceSegment(segment_key=f"m63d-{state['token']}", name="M6.3D race")
        repository = AudienceSegmentRepository(setup)
        repository.create_segment(segment)
        revision = repository.create_revision_or_reuse(AudienceSegmentRevision(
            segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1",
            definition_fingerprint=segment_definition_fingerprint(definition), definition_json=definition.to_dict(),
        ))
        setup.commit()
        profile_snapshot = (profile.profile_id, profile.source_fingerprint)
        revision_snapshot = (revision.id, revision.definition_fingerprint, revision.definition_json)
    except Exception:
        setup.rollback()
        raise
    finally:
        setup.close()

    gate = threading.Barrier(2)
    original = AudienceSegmentMembershipRepository.create_or_reuse

    def synchronized_create_or_reuse(self, *args, **kwargs):
        gate.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AudienceSegmentMembershipRepository, "create_or_reuse", synchronized_create_or_reuse)
    try:
        results = _run_two_callers(
            factory,
            lambda db: AudienceSegmentMembershipService(db).evaluate(profile.profile_id, revision.id),
        )
        monkeypatch.setattr(AudienceSegmentMembershipRepository, "create_or_reuse", original)
        assert len(results) == 2
        assert len({result.membership_id for result in results}) == 1
        assert len({result.is_member for result in results}) == 1
        verifier = factory()
        try:
            memberships = verifier.query(AudienceSegmentMembership).filter_by(
                segment_revision_id=revision.id, profile_id=profile.profile_id,
            ).all()
            assert len(memberships) == 1
            winner = memberships[0]
            assert winner.id == results[0].membership_id and winner.is_member is True
            assert (profile.profile_id, verifier.get(AudienceProfile, profile.profile_id).source_fingerprint) == profile_snapshot
            stored_revision = verifier.get(AudienceSegmentRevision, revision.id)
            assert (stored_revision.id, stored_revision.definition_fingerprint, stored_revision.definition_json) == revision_snapshot
            winner_evaluated_at = winner.evaluated_at
            repeat = AudienceSegmentMembershipService(verifier).evaluate(profile.profile_id, revision.id)
            verifier.commit()
            verifier.expire_all()
            assert repeat.membership_id == winner.id
            assert verifier.get(AudienceSegmentMembership, winner.id).evaluated_at == winner_evaluated_at
        finally:
            verifier.close()
    finally:
        _cleanup(engine, state)
