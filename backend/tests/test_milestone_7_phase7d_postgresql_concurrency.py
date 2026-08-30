"""Guarded G5 convergence proof for complete immutable M7C assessment evaluation."""

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

from app.audience.contextual_qualification import qualify_contextually
from app.audience.contextual_qualification_contracts import ContextualQualificationInput
from app.audience.intent_scoring import score_intent
from app.audience.intent_scoring_contracts import IntentScoringInput
from app.audience.qualification_contracts import (
    DIMENSIONS, QualificationContext, QualificationRuleset, context_fingerprint,
    qualification_ruleset_fingerprint, selected_membership_fingerprint,
)
from app.models.audience import (
    AudienceProfile, AudienceQualificationAssessment, AudienceQualificationAssessmentMembership,
    AudienceQualificationContribution, AudienceSegment, AudienceSegmentMembership,
    AudienceSegmentRevision,
)
from app.repositories.audience_qualification_repository import AudienceQualificationRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_qualification_evaluation_service import AudienceQualificationEvaluationService
from app.services.audience_segment_membership_service import AudienceSegmentMembershipService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate


REVISION = "d8e9f0a1b2c3"
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


def _ruleset():
    intent = {dimension: 0 for dimension in DIMENSIONS}
    intent["pricing_intent"] = 100
    qualification = {dimension: 0 for dimension in DIMENSIONS}
    qualification["pricing_intent"] = 50
    qualification["business_need_fit"] = 50
    return QualificationRuleset(
        "m7d-v1",
        {"PROBLEM": ("problem_strength",), "INTEREST": ("interest_alignment",),
         "INTENT": ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent"),
         "PURCHASE": ("purchase_signal",), "ENGAGEMENT": ("engagement",), "BUSINESS_NEED": ("business_need_fit",)},
        {"RESEARCH": 20, "COMPARE": 40, "EVALUATE": 60, "PRICING": 80, "PURCHASE_REQUEST": 100},
        "MULTIPLY_CONFIDENCE_CAP", {dimension: 100 for dimension in DIMENSIONS},
        intent, qualification,
        {"NOT_QUALIFIED": 0, "EARLY": 40, "QUALIFIED": 60, "HIGH_INTENT": 80},
    )


def _seed(factory):
    db, token = factory(), uuid4().hex
    try:
        foundation = AudienceFoundationService(db)
        subject = foundation.create_subject("ORGANIZATION")
        observation = foundation.ingest_observation(
            research_run_id=None, subject_id=subject.id, source_namespace="m7d-race",
            source_type="MANUAL", external_observation_id=token, source_reference=f"observation:{token}",
            observed_at=AS_OF, normalized_fact={"token": token},
        )
        evidence = foundation.record_evidence(
            observation_id=observation.id, source_reference=f"evidence:{token}",
            normalized_representation={"token": token}, content_fingerprint=(token * 2)[:64],
        )
        intent = AudienceSignalService(db).persist(
            SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "m7d-v1"),
            subject_id=subject.id,
        )
        need = AudienceSignalService(db).persist(
            SignalCandidate("BUSINESS_NEED", "hosting", "Hosting", None, 50, 60, [evidence.id], "m7d-v1"),
            subject_id=subject.id,
        )
        profile = AudienceProfileService(db).derive(subject.id, effective_as_of=AS_OF)
        segment = AudienceSegment(segment_key=f"m7d-{token}", name="M7D required")
        db.add(segment); db.flush()
        revision = AudienceSegmentRevision(
            segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1",
            definition_fingerprint="a" * 64,
            definition_json={"all_of": [{"signal_type": "INTENT", "topic": "hosting", "intent_stage": "PRICING", "minimum_strength": None, "minimum_confidence": None, "max_age_days": None}], "allowed_subject_types": ["ORGANIZATION"]},
        )
        db.add(revision); db.flush()
        membership = AudienceSegmentMembership(segment_revision_id=revision.id, profile_id=profile.profile_id, is_member=True)
        db.add(membership); db.commit()
        return {"token": token, "subject_id": subject.id, "observation_id": observation.id, "evidence_id": evidence.id,
                "signal_ids": (intent.id, need.id), "profile_id": profile.profile_id, "segment_id": segment.id,
                "revision_id": revision.id, "membership_id": membership.id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _expected(factory, state, ruleset, context):
    db = factory()
    try:
        profile = db.get(AudienceProfile, state["profile_id"])
        facts = AudienceSegmentMembershipService(db)._facts(profile)
        scoring = score_intent(IntentScoringInput(facts, profile.effective_as_of, ruleset))
        contextual = qualify_contextually(ContextualQualificationInput(
            scoring, facts, "ORGANIZATION", context, ruleset, ((state["revision_id"], True),)
        ))
        contributions = tuple(scoring.contributions) + tuple(contextual.contributions)
        return ({**scoring.dimensions, "business_need_fit": contextual.business_need_fit}, scoring.intent_score,
                contextual.qualification_score, contextual.qualification_status, contributions)
    finally:
        db.close()


def _contribution_set(rows):
    return {(row.source_signal_id, row.dimension, row.rule_id, row.strength, row.confidence,
             row.raw_amount, row.confidence_adjusted_amount, row.final_amount, row.disposition) for row in rows}


def _cleanup(engine, state):
    with engine.begin() as connection:
        assessment_ids = "SELECT id FROM audience_qualification_assessments WHERE profile_id=:profile_id"
        connection.execute(text(f"DELETE FROM audience_qualification_contributions WHERE assessment_id IN ({assessment_ids})"), state)
        connection.execute(text(f"DELETE FROM audience_qualification_assessment_memberships WHERE assessment_id IN ({assessment_ids})"), state)
        connection.execute(text("DELETE FROM audience_qualification_assessments WHERE profile_id=:profile_id"), state)
        connection.execute(text("DELETE FROM audience_segment_memberships WHERE id=:membership_id"), state)
        connection.execute(text("DELETE FROM audience_segment_revisions WHERE id=:revision_id"), state)
        connection.execute(text("DELETE FROM audience_segments WHERE id=:segment_id"), state)
        connection.execute(text("DELETE FROM audience_profile_signals WHERE profile_id=:profile_id"), state)
        connection.execute(text("DELETE FROM audience_profiles WHERE id=:profile_id"), state)
        signal_state = {"signal_ids": list(state["signal_ids"])}
        connection.execute(text("DELETE FROM audience_signal_evidence WHERE signal_id = ANY(:signal_ids)"), signal_state)
        connection.execute(text("DELETE FROM audience_signals WHERE id = ANY(:signal_ids)"), signal_state)
        connection.execute(text("DELETE FROM audience_evidence WHERE id=:evidence_id"), state)
        connection.execute(text("DELETE FROM audience_observations WHERE id=:observation_id"), state)
        connection.execute(text("DELETE FROM audience_subjects WHERE id=:subject_id"), state)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audience_qualification_assessments WHERE profile_id=:profile_id"), state).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM audience_segment_memberships WHERE id=:membership_id"), state).scalar_one() == 0


def test_postgresql_concurrent_identical_m7c_evaluation_converges(factory, engine, monkeypatch):
    state, ruleset, context = _seed(factory), _ruleset(), QualificationContext("TOPIC", topic="hosting")
    dimensions, intent_score, qualification_score, qualification_status, expected_contributions = _expected(factory, state, ruleset, context)
    gate, start = threading.Barrier(2), threading.Barrier(3)
    hits, results, errors, pids = [], [], [], []
    lock = threading.Lock()
    original = AudienceQualificationRepository.create_or_reuse

    def synchronized_create_or_reuse(self, *args, **kwargs):
        with lock:
            hits.append(1)
        gate.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AudienceQualificationRepository, "create_or_reuse", synchronized_create_or_reuse)

    def caller():
        db = factory()
        try:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with lock:
                pids.append(pid)
            start.wait(timeout=10)
            result = AudienceQualificationEvaluationService(db).evaluate(state["profile_id"], ruleset, context, (state["membership_id"],))
            assert db.in_transaction()
            db.commit()
            with lock:
                results.append((result.assessment_id, intent_score, qualification_score, qualification_status))
        except Exception as error:
            db.rollback()
            with lock:
                errors.append(error)
        finally:
            db.close()

    threads = [threading.Thread(target=caller) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        start.wait(timeout=10)
        for thread in threads:
            thread.join(20)
        assert all(not thread.is_alive() for thread in threads)
        assert len(hits) == 2 and len(pids) == 2 and pids[0] != pids[1]
        assert errors == [] and not any(isinstance(error, IntegrityError) for error in errors)
        assert len(results) == 2 and len(set(results)) == 1

        verifier = factory()
        try:
            assessment_id = results[0][0]
            assessments = verifier.query(AudienceQualificationAssessment).filter_by(
                profile_id=state["profile_id"], scoring_ruleset_version=ruleset.version,
                scoring_ruleset_fingerprint=qualification_ruleset_fingerprint(ruleset),
                context_fingerprint=context_fingerprint(context),
                selected_membership_fingerprint=selected_membership_fingerprint((state["membership_id"],)),
            ).all()
            assert len(assessments) == 1 and assessments[0].id == assessment_id
            stored = assessments[0]
            assert {dimension: getattr(stored, dimension) for dimension in DIMENSIONS} == dimensions
            assert (stored.intent_score, stored.qualification_score, stored.qualification_status, stored.derived_at) == (intent_score, qualification_score, qualification_status, AS_OF)
            junctions = verifier.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=assessment_id).all()
            assert [row.membership_id for row in junctions] == [state["membership_id"]]
            contributions = verifier.query(AudienceQualificationContribution).filter_by(assessment_id=assessment_id).all()
            assert _contribution_set(contributions) == _contribution_set(expected_contributions)
            assert len(contributions) == len(_contribution_set(contributions))
            assert {row.dimension for row in contributions} >= {"pricing_intent", "business_need_fit"}
        finally:
            verifier.close()
        assert engine.pool.checkedout() == 0
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid <> pg_backend_pid()")).scalar_one() == 0
    finally:
        _cleanup(engine, state)
