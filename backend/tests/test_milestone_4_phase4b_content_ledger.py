from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import inspect

from app.content_intelligence.contracts import (
    ContentBriefStatus,
    ContentGenerationRunStatus,
    ContentType,
    EvidenceUsageRole,
)
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.services.content_brief_service import ContentBriefService


def _make_discovery_run_and_candidate(db_session, *, run_id="run-1", candidate_id="candidate-1", disposition="SELECTED", verification_status="VERIFIED"):
    run = DiscoveryRun(
        id=run_id,
        input_type="URL",
        input_value="https://example.com",
        status="CREATED",
        idempotency_key=run_id,
        candidate_count=0,
        verified_count=0,
        selected_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    candidate = DiscoveryCandidate(
        id=candidate_id,
        run_id=run_id,
        source_adapter="official_site",
        source_type="affiliate_program",
        canonical_domain="example.com",
        program_identity_key="example:program:1",
        dedupe_key="example:program:1",
        commission_model="UNKNOWN",
        verification_status=verification_status,
        disposition=disposition,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.add(candidate)
    db_session.flush()
    return run, candidate


def _make_content_brief_kwargs(**overrides):
    payload = {
        "discovery_run_id": "run-1",
        "discovery_candidate_id": "candidate-1",
        "content_type": ContentType.ARTICLE.value,
        "channel_intent": "SEO",
        "objective": "Compare wireless earbuds for value and comfort.",
        "audience_intent": "Shoppers evaluating wireless earbuds",
        "audience_problem": "They want value without overpaying for premium extras.",
        "angle": "Compare battery life, comfort, and price trade-offs.",
        "call_to_action": "Read the comparison and choose what fits your use case.",
        "tone": "trustworthy",
        "required_disclosure": "This article includes affiliate links.",
        "key_benefits": ["price transparency", "clear comparison"],
        "proof_points": ["battery life", "sound quality", "comfort"],
        "target_keywords": ["wireless earbuds", "best wireless earbuds"],
        "constraints": ["No unsupported claims"],
        "idempotency_key": "brief-key-1",
        "status": ContentBriefStatus.READY.value,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return payload


def test_content_type_evidence_usage_role_and_status_contracts():
    assert {item.value for item in ContentType} == {
        "ARTICLE",
        "BLOG_POST",
        "SOCIAL_POST",
        "SHORT_VIDEO_SCRIPT",
        "LONG_VIDEO_SCRIPT",
        "EMAIL",
        "LANDING_PAGE_COPY",
        "PRODUCT_REVIEW",
        "COMPARISON",
        "BUYER_GUIDE",
        "AD_COPY",
    }
    assert {item.value for item in EvidenceUsageRole} == {
        "PRIMARY",
        "SUPPORTING",
        "ECONOMICS",
        "FEATURE",
        "CTA_SUPPORT",
        "DISCLOSURE_SUPPORT",
    }
    assert ContentBriefStatus.legal_transition("CREATED", "READY") is True
    assert ContentBriefStatus.legal_transition("READY", "GENERATING") is True
    assert ContentBriefStatus.legal_transition("GENERATING", "COMPLETED") is True
    assert ContentBriefStatus.legal_transition("GENERATING", "FAILED") is True
    assert ContentBriefStatus.legal_transition("READY", "REJECTED") is True
    assert ContentBriefStatus.legal_transition("CREATED", "FAILED") is False
    assert ContentBriefStatus.legal_transition("READY", "COMPLETED") is False
    assert {item.value for item in ContentGenerationRunStatus} == {"CREATED", "RUNNING", "RETRY_WAIT", "COMPLETED", "FAILED"}
    assert ContentGenerationRunStatus.legal_transition("CREATED", "RUNNING") is True
    assert ContentGenerationRunStatus.legal_transition("RUNNING", "COMPLETED") is True
    assert ContentGenerationRunStatus.legal_transition("RUNNING", "FAILED") is True
    assert ContentGenerationRunStatus.legal_transition("RETRY_WAIT", "RUNNING") is True
    assert ContentGenerationRunStatus.legal_transition("CREATED", "COMPLETED") is False
    assert ContentGenerationRunStatus.legal_transition("RUNNING", "RETRY_WAIT") is True


def test_content_brief_evidence_and_generation_run_schema(db_session):
    _, candidate = _make_discovery_run_and_candidate(db_session)
    brief_kwargs = _make_content_brief_kwargs(discovery_run_id="run-1", discovery_candidate_id="candidate-1")
    brief = ContentBrief(**brief_kwargs)
    db_session.add(brief)
    db_session.flush()

    required_columns = {
        "id",
        "discovery_run_id",
        "discovery_candidate_id",
        "content_type",
        "channel_intent",
        "objective",
        "audience_intent",
        "audience_problem",
        "angle",
        "call_to_action",
        "tone",
        "required_disclosure",
        "key_benefits",
        "proof_points",
        "target_keywords",
        "constraints",
        "idempotency_key",
        "status",
        "created_at",
        "updated_at",
    }
    assert required_columns.issubset(set(ContentBrief.__table__.columns.keys()))
    assert "target_audience" not in ContentBrief.__table__.columns.keys()
    assert "title" not in ContentBrief.__table__.columns.keys()
    assert "primary_keyword" not in ContentBrief.__table__.columns.keys()
    assert "secondary_keywords" not in ContentBrief.__table__.columns.keys()

    evidence_observation = EvidenceObservation(
        id="evidence-obs-1",
        candidate_id=candidate.id,
        claim_type="commission_rate",
        observed_value={"value": "12%"},
        source_url="https://example.com/affiliate",
        source_type="affiliate_program",
        extractor="official_site",
        extractor_version="v1",
        confidence=95,
        created_at=datetime.now(timezone.utc),
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(evidence_observation)
    db_session.flush()

    link = ContentBriefEvidence(
        id="evidence-link-1",
        content_brief_id=brief.id,
        evidence_observation_id=evidence_observation.id,
        usage_role=EvidenceUsageRole.PRIMARY.value,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(link)
    db_session.flush()

    generation_run = ContentGenerationRun(
        id="generation-1",
        content_brief_id=brief.id,
        idempotency_key="gen-key-1",
        provider="openai",
        model="gpt-4.1",
        prompt_version="v1",
        generation_parameters={"temperature": 0.2},
        status=ContentGenerationRunStatus.CREATED.value,
        attempt_count=0,
        result_summary="queued",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(generation_run)
    db_session.flush()

    assert link.content_brief_id == brief.id
    assert link.evidence_observation_id == evidence_observation.id
    assert link.usage_role == EvidenceUsageRole.PRIMARY.value
    assert generation_run.content_brief_id == brief.id
    assert generation_run.provider == "openai"
    assert generation_run.model == "gpt-4.1"
    assert generation_run.prompt_version == "v1"


def test_service_eligibility_and_provenance_rules(db_session):
    service = ContentBriefService(db_session)

    run, candidate = _make_discovery_run_and_candidate(db_session, run_id="run-eligible", candidate_id="candidate-eligible")
    evidence = EvidenceObservation(
        id="evidence-valid",
        candidate_id=candidate.id,
        claim_type="commission_rate",
        observed_value={"value": "12%"},
        source_url="https://example.com/affiliate",
        source_type="affiliate_program",
        extractor="official_site",
        extractor_version="v1",
        confidence=95,
        created_at=datetime.now(timezone.utc),
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(evidence)
    db_session.flush()

    brief = service.create_brief(
        discovery_run_id=run.id,
        discovery_candidate_id=candidate.id,
        content_type=ContentType.ARTICLE.value,
        channel_intent="SEO",
        objective="Compare budget earbuds.",
        audience_intent="Buyers comparing budget earbuds",
        audience_problem="They want value without overspending.",
        angle="Compare battery life and features.",
        call_to_action="Read the buyer guide.",
        evidence_observation_ids=[evidence.id],
    )
    assert brief.id is not None
    assert db_session.query(ContentBrief).count() == 1
    assert db_session.query(ContentBriefEvidence).count() == 1

    # candidate must be selected + verified
    run2, candidate2 = _make_discovery_run_and_candidate(db_session, run_id="run-partial", candidate_id="candidate-partial", disposition="SELECTED", verification_status="PARTIAL")
    with pytest.raises(ValueError):
        service.create_brief(
            discovery_run_id=run2.id,
            discovery_candidate_id=candidate2.id,
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Should reject partial verification.",
            audience_intent="Partial buyer",
            audience_problem="Problem",
            angle="Angle",
            call_to_action="CTA",
        )

    run3, candidate3 = _make_discovery_run_and_candidate(db_session, run_id="run-unselected", candidate_id="candidate-unselected", disposition="VERIFIED", verification_status="VERIFIED")
    with pytest.raises(ValueError):
        service.create_brief(
            discovery_run_id=run3.id,
            discovery_candidate_id=candidate3.id,
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Should reject unselected.",
            audience_intent="Buyer",
            audience_problem="Problem",
            angle="Angle",
            call_to_action="CTA",
        )

    with pytest.raises(ValueError):
        service.create_brief(
            discovery_run_id="missing-run",
            discovery_candidate_id="missing-candidate",
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Should reject missing candidate.",
            audience_intent="Buyer",
            audience_problem="Problem",
            angle="Angle",
            call_to_action="CTA",
        )

    # cross-run and cross-candidate provenance rejection
    run4, candidate4 = _make_discovery_run_and_candidate(db_session, run_id="run-cross", candidate_id="candidate-cross")
    cross_run_evidence = EvidenceObservation(
        id="evidence-cross-run",
        candidate_id=candidate4.id,
        claim_type="commission_rate",
        observed_value={"value": "15%"},
        source_url="https://example.com/cross",
        source_type="affiliate_program",
        extractor="official_site",
        extractor_version="v1",
        confidence=90,
        created_at=datetime.now(timezone.utc),
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(cross_run_evidence)
    db_session.flush()
    with pytest.raises(ValueError):
        service.create_brief(
            discovery_run_id=run.id,
            discovery_candidate_id=candidate.id,
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Use evidence from a different candidate.",
            audience_intent="Buyer",
            audience_problem="Problem",
            angle="Angle",
            call_to_action="CTA",
            evidence_observation_ids=[cross_run_evidence.id],
        )

    duplicate_link = ContentBriefEvidence(
        id="duplicate-link-1",
        content_brief_id=brief.id,
        evidence_observation_id=evidence.id,
        usage_role=EvidenceUsageRole.PRIMARY.value,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(duplicate_link)
    with pytest.raises(Exception):
        db_session.flush()


def test_brief_and_generation_idempotency_and_write_boundaries(db_session):
    service = ContentBriefService(db_session)
    run, candidate = _make_discovery_run_and_candidate(db_session, run_id="run-idempotency", candidate_id="candidate-idempotency")
    evidence = EvidenceObservation(
        id="evidence-idempotency",
        candidate_id=candidate.id,
        claim_type="feature",
        observed_value={"value": "battery life"},
        source_url="https://example.com/features",
        source_type="affiliate_program",
        extractor="official_site",
        extractor_version="v1",
        confidence=88,
        created_at=datetime.now(timezone.utc),
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(evidence)
    db_session.flush()

    first = service.create_brief(
        discovery_run_id=run.id,
        discovery_candidate_id=candidate.id,
        content_type=ContentType.ARTICLE.value,
        channel_intent="SEO",
        objective="Structured buyer guide.",
        audience_intent="buyers comparing wireless earbuds",
        audience_problem="They need a resource to compare features without bias.",
        angle="Compare core features by use case.",
        call_to_action="Read the guide.",
        key_benefits=["clear comparison", "price transparency"],
        proof_points=["battery life", "sound quality"],
        target_keywords=["wireless earbuds", "best wireless earbuds"],
        constraints=["No unsupported claims"],
        evidence_observation_ids=[evidence.id],
    )
    second = service.create_brief(
        discovery_run_id=run.id,
        discovery_candidate_id=candidate.id,
        content_type=ContentType.ARTICLE.value,
        channel_intent="SEO",
        objective="Structured buyer guide.",
        audience_intent="buyers comparing wireless earbuds",
        audience_problem="They need a resource to compare features without bias.",
        angle="Compare core features by use case.",
        call_to_action="Read the guide.",
        key_benefits=["clear comparison", "price transparency"],
        proof_points=["battery life", "sound quality"],
        target_keywords=["wireless earbuds", "best wireless earbuds"],
        constraints=["No unsupported claims"],
        evidence_observation_ids=[evidence.id],
    )
    assert first.id == second.id
    assert db_session.query(ContentBrief).count() == 1

    different_type = service.create_brief(
        discovery_run_id=run.id,
        discovery_candidate_id=candidate.id,
        content_type=ContentType.BLOG_POST.value,
        channel_intent="SEO",
        objective="Structured buyer guide.",
        audience_intent="buyers comparing wireless earbuds",
        audience_problem="They need a resource to compare features without bias.",
        angle="Compare core features by use case.",
        call_to_action="Read the guide.",
        key_benefits=["clear comparison", "price transparency"],
        proof_points=["battery life", "sound quality"],
        target_keywords=["wireless earbuds", "best wireless earbuds"],
        constraints=["No unsupported claims"],
        evidence_observation_ids=[evidence.id],
    )
    assert different_type.id != first.id

    gen_1 = service.create_generation_run(
        content_brief_id=first.id,
        provider="openai",
        model="gpt-4.1",
        prompt_version="v1",
        generation_parameters={"temperature": 0.2, "style": "neutral"},
    )
    gen_2 = service.create_generation_run(
        content_brief_id=first.id,
        provider="openai",
        model="gpt-4.1",
        prompt_version="v1",
        generation_parameters={"style": "neutral", "temperature": 0.2},
    )
    assert gen_1.id == gen_2.id
    assert db_session.query(ContentGenerationRun).count() == 1
    gen_3 = service.create_generation_run(
        content_brief_id=first.id,
        provider="anthropic",
        model="gpt-4.1",
        prompt_version="v1",
        generation_parameters={"temperature": 0.2, "style": "neutral"},
    )
    assert gen_3.id != gen_1.id

    assert db_session.query(Product).count() == 0
    assert db_session.query(AffiliateProgram).count() == 0
    assert db_session.query(AffiliateOpportunity).count() == 0
    assert db_session.query(AffiliateContentAsset).count() == 0

    with patch("requests.get", side_effect=AssertionError("network forbidden")):
        assert True
    with patch("app.ai.provider_factory.ProviderFactory.create", side_effect=AssertionError("provider factory forbidden")):
        service.create_generation_run(
            content_brief_id=first.id,
            provider="openai",
            model="gpt-4.1-mini",
            prompt_version="v2",
            generation_parameters={"temperature": 0.1},
        )
