from datetime import datetime, timedelta, timezone
import socket

import pytest
from sqlalchemy.exc import IntegrityError

from app.distribution.contracts import CreateDistributionRunRequest, DistributionRunStatus
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.services.distribution_run_service import DistributionRunService


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    import app.database.session as database_session

    calls = []

    def forbidden(*args, **kwargs):
        calls.append("external/configured access")
        raise AssertionError("Phase 5B domain tests must not use configured DB, network, or providers")

    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            forbidden(*args, **kwargs)

    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    yield
    assert calls == []


def source(db):
    now = datetime.now(timezone.utc)
    run = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    generation = ContentGenerationRun(id="generation", content_brief_id="brief", idempotency_key="generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    artifact = GeneratedContentArtifact(id="artifact", generation_run_id="generation", content_brief_id="brief", content_type="ARTICLE", title="Title", hook="Hook", body="Body", call_to_action="CHECK_DETAILS", affiliate_disclosure="Affiliate disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now)
    evaluation = ContentEvaluation(id="evaluation", artifact_id="artifact", content_brief_id="brief", generation_run_id="generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)
    db.add_all([run, candidate, brief, generation, artifact, evaluation])
    db.commit()
    return artifact, evaluation


def request(**changes):
    values = dict(generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform=" WordPress ", account_reference=" primary   site ", destination=" blog   /main ")
    values.update(changes)
    return CreateDistributionRunRequest(**values)


def test_immediate_creation_has_approved_lineage_and_empty_external_result(db_session):
    source(db_session)
    row = DistributionRunService(db_session).create(request())
    assert row.status == DistributionRunStatus.CREATED.value
    assert (row.generated_content_artifact_id, row.content_evaluation_id, row.platform, row.account_reference, row.destination) == ("artifact", "evaluation", "wordpress", "primary site", "blog /main")
    assert row.scheduled_for is row.external_post_id is row.external_url is row.result_metadata is row.failure_category is row.error_summary is row.publishing_started_at is row.completed_at is None


def test_future_aware_schedule_is_utc_and_scheduled_while_naive_is_rejected(db_session):
    source(db_session)
    future = datetime.now(timezone(timedelta(hours=2))) + timedelta(days=1)
    row = DistributionRunService(db_session).create(request(scheduled_for=future))
    assert row.status == DistributionRunStatus.SCHEDULED.value and row.scheduled_for.tzinfo == timezone.utc
    past = DistributionRunService(db_session).create(request(prepared_content_body="past", scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert past.status == DistributionRunStatus.CREATED.value
    with pytest.raises(ValueError, match="timezone-aware"):
        DistributionRunService(db_session).create(request(prepared_content_body="naive", scheduled_for=datetime.now()))


@pytest.mark.parametrize("change,error", [
    ({"generated_content_artifact_id": "missing"}, "artifact does not exist"),
    ({"content_evaluation_id": "missing"}, "evaluation does not exist"),
    ({"prepared_content_body": object()}, "prepared_content_body must be text"),
    ({"platform": " \t "}, "platform is required"),
    ({"account_reference": ""}, "account_reference is required"),
    ({"destination": object()}, "destination must be text"),
])
def test_invalid_creation_inputs_are_rejected_deterministically(db_session, change, error):
    source(db_session)
    with pytest.raises(ValueError, match=error):
        DistributionRunService(db_session).create(request(**change))


@pytest.mark.parametrize("decision,approved", [("REJECTED", False), ("REVISION_REQUIRED", False), ("APPROVED", False)])
def test_only_approved_evaluation_authorizes_distribution(db_session, decision, approved):
    _, evaluation = source(db_session)
    evaluation.decision, evaluation.approved = decision, approved
    db_session.commit()
    with pytest.raises(ValueError, match="not approved"):
        DistributionRunService(db_session).create(request())


def test_evaluation_must_match_artifact_generation_and_brief_lineage(db_session):
    _, evaluation = source(db_session)
    for field, value in (("artifact_id", "other-artifact"), ("generation_run_id", "other-generation"), ("content_brief_id", "other-brief")):
        setattr(evaluation, field, value)
        db_session.commit()
        with pytest.raises(ValueError, match="does not match artifact lineage"):
            DistributionRunService(db_session).create(request())
        setattr(evaluation, field, {"artifact_id": "artifact", "generation_run_id": "generation", "content_brief_id": "brief"}[field])
        db_session.commit()


def test_idempotency_key_is_deterministic_and_sensitive_to_each_identity_component(db_session):
    source(db_session)
    service = DistributionRunService(db_session)
    base = service.create(request())
    fingerprint = service.payload_fingerprint("Body")
    assert base.payload_fingerprint == fingerprint
    assert base.idempotency_key == service.idempotency_key(artifact_id="artifact", evaluation_id="evaluation", platform="wordpress", account_reference="primary site", destination="blog /main", payload_fingerprint=fingerprint)
    keys = {
        service.idempotency_key(artifact_id="artifact", evaluation_id="evaluation", platform=platform, account_reference=account, destination=destination, payload_fingerprint=fingerprint)
        for platform, account, destination, fingerprint in [
            ("telegram_channel", "primary site", "blog /main", fingerprint),
            ("wordpress", "other", "blog /main", fingerprint),
            ("wordpress", "primary site", "other", fingerprint),
            ("wordpress", "primary site", "blog /main", service.payload_fingerprint("other")),
        ]
    }
    assert len(keys) == 4 and base.idempotency_key not in keys


def test_duplicate_and_restart_like_creation_return_one_durable_run(db_session, db_session_factory):
    source(db_session)
    first = DistributionRunService(db_session).create(request())
    assert DistributionRunService(db_session).create(request()).id == first.id
    restarted = db_session_factory()
    try:
        assert DistributionRunService(restarted).create(request()).id == first.id
    finally:
        restarted.close()
    assert db_session.query(DistributionRun).count() == 1


def test_database_unique_constraint_remains_final_creation_authority(db_session):
    source(db_session)
    row = DistributionRunService(db_session).create(request())
    db_session.add(DistributionRun(generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform="wordpress", account_reference="primary site", destination="blog /main", status="CREATED", idempotency_key=row.idempotency_key, prepared_content_body="Body", payload_fingerprint=row.payload_fingerprint))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_one_artifact_supports_multiple_independent_destinations(db_session):
    source(db_session)
    service = DistributionRunService(db_session)
    first = service.create(request())
    second = service.create(request(destination="blog /secondary"))
    third = service.create(request(platform="telegram_channel", destination="@etm"))
    assert len({first.id, second.id, third.id}) == 3
    assert len(service.runs.list_by_artifact("artifact")) == 3


def test_identity_is_not_exposed_through_a_broad_update_path_and_legacy_is_untouched(db_session):
    source(db_session)
    service = DistributionRunService(db_session)
    row = service.create(request())
    assert not hasattr(service.runs, "update") and not hasattr(service.runs, "publish")
    assert row.idempotency_key.startswith("distribution-run:")
    assert "token" not in DistributionRun.__table__.columns and "password" not in DistributionRun.__table__.columns and "api_secret" not in DistributionRun.__table__.columns
    from app.models.publishing_queue import PublishingQueue
    assert db_session.query(PublishingQueue).count() == 0
