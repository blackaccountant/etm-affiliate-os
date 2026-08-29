from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.content_intelligence.brief_builder import (
    AFFILIATE_DISCLOSURE_REQUIRED,
    MANDATORY_CONSTRAINTS,
    ContentBriefBuildRequest,
    ContentBriefBuilderService,
)
from app.content_intelligence.contracts import ContentType, EvidenceUsageRole
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.product import Product
from app.services.content_brief_service import ContentBriefService


def _run_and_candidate(
    db_session,
    *,
    run_id="run-4c",
    candidate_id="candidate-4c",
    disposition="SELECTED",
    verification_status="VERIFIED",
):
    run = DiscoveryRun(
        id=run_id,
        input_type="URL",
        input_value="https://example.com",
        status="COMPLETED",
        idempotency_key=run_id,
        candidate_count=1,
        verified_count=1,
        selected_count=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    candidate = DiscoveryCandidate(
        id=candidate_id,
        run_id=run_id,
        source_adapter="official_site",
        source_type="official_site",
        source_url="https://example.com/affiliate",
        vendor_name="Example Vendor",
        program_name="Example Partner Program",
        offer_name="Example Offer",
        canonical_domain="example.com",
        affiliate_network="Impact",
        program_identity_key=f"program:{candidate_id}",
        dedupe_key=f"candidate:{candidate_id}",
        commission_model="PERCENT",
        verification_status=verification_status,
        disposition=disposition,
        confidence=95,
        score=90,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add_all([run, candidate])
    db_session.flush()
    return run, candidate


def _evidence(db_session, candidate, claim_type, observed_value, *, evidence_id=None, source_url="https://example.com/affiliate"):
    record = EvidenceObservation(
        id=evidence_id or f"evidence-{claim_type}-{db_session.query(EvidenceObservation).count()}",
        candidate_id=candidate.id,
        claim_type=claim_type,
        observed_value=observed_value,
        source_url=source_url,
        source_type="official_site",
        excerpt=f"Observed {claim_type}",
        extractor="official-site-parser",
        extractor_version="2.0.0",
        confidence=95,
        observed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(record)
    db_session.flush()
    return record


def _request(**overrides):
    payload = {
        "discovery_run_id": "run-4c",
        "discovery_candidate_id": "candidate-4c",
        "content_type": ContentType.ARTICLE.value,
        "channel_intent": "SEO",
        "objective": "Document verified affiliate-program facts.",
        "audience_intent": "comparison research",
        "audience_problem": "Needs verified program details.",
        "target_keywords": ("Example Vendor Review",),
        "constraints": ("EDITORIAL_NEUTRALITY",),
    }
    payload.update(overrides)
    return ContentBriefBuildRequest(**payload)


def test_selected_verified_candidate_builds_grounded_ready_brief(db_session):
    _, candidate = _run_and_candidate(db_session)
    program = _evidence(db_session, candidate, "affiliate_program_exists", True)
    commission = _evidence(db_session, candidate, "commission_percent", 12)
    offer = _evidence(db_session, candidate, "affiliate_url", "https://example.com/partners/apply")

    brief = ContentBriefBuilderService(db_session).build(_request())

    assert brief.status == "READY"
    assert brief.key_benefits == []
    assert brief.required_disclosure == AFFILIATE_DISCLOSURE_REQUIRED
    assert brief.audience_intent == "comparison research"
    assert brief.audience_problem == "Needs verified program details."
    assert brief.call_to_action == "VISIT_OFFER"
    assert set(MANDATORY_CONSTRAINTS).issubset(set(brief.constraints))
    assert "EDITORIAL_NEUTRALITY" in brief.constraints
    assert brief.target_keywords == sorted(brief.target_keywords)
    assert all("volume" not in keyword and "cpc" not in keyword for keyword in brief.target_keywords)

    by_evidence = {point["evidence_observation_id"]: point for point in brief.proof_points}
    assert by_evidence[program.id]["usage_role"] == EvidenceUsageRole.PRIMARY.value
    assert by_evidence[commission.id]["usage_role"] == EvidenceUsageRole.ECONOMICS.value
    assert by_evidence[offer.id]["usage_role"] == EvidenceUsageRole.CTA_SUPPORT.value
    assert by_evidence[commission.id]["source_url"] == "https://example.com/affiliate"
    assert {link.usage_role for link in db_session.query(ContentBriefEvidence).all()} == {
        EvidenceUsageRole.PRIMARY.value,
        EvidenceUsageRole.ECONOMICS.value,
        EvidenceUsageRole.CTA_SUPPORT.value,
    }


@pytest.mark.parametrize(
    ("disposition", "verification_status", "message"),
    [
        ("DISCOVERED", "VERIFIED", "not selected"),
        ("SELECTED", "PARTIAL", "not verified"),
        ("SELECTED", "UNVERIFIED", "not verified"),
        ("SELECTED", "STALE", "not verified"),
    ],
)
def test_builder_rejects_ineligible_candidates(db_session, disposition, verification_status, message):
    _, candidate = _run_and_candidate(db_session, disposition=disposition, verification_status=verification_status)
    _evidence(db_session, candidate, "affiliate_program_exists", True)

    with pytest.raises(ValueError, match=message):
        ContentBriefBuilderService(db_session).build(_request())


def test_builder_rejects_missing_candidate_wrong_run_and_missing_valid_evidence(db_session):
    _run_and_candidate(db_session)
    builder = ContentBriefBuilderService(db_session)

    with pytest.raises(ValueError, match="candidate not found"):
        builder.build(_request(discovery_candidate_id="missing"))
    with pytest.raises(ValueError, match="run not found"):
        builder.build(_request(discovery_run_id="missing"))

    other_run, other_candidate = _run_and_candidate(db_session, run_id="other-run", candidate_id="other-candidate")
    _evidence(db_session, other_candidate, "affiliate_program_exists", True)
    with pytest.raises(ValueError, match="does not belong"):
        builder.build(_request(discovery_candidate_id=other_candidate.id))

    _, no_evidence_candidate = _run_and_candidate(db_session, run_id="empty-run", candidate_id="empty-candidate")
    with pytest.raises(ValueError, match="evidence observation"):
        builder.build(_request(discovery_run_id="empty-run", discovery_candidate_id=no_evidence_candidate.id))


def test_economics_conflicts_are_retained_and_missing_economics_are_omitted(db_session):
    _, candidate = _run_and_candidate(db_session)
    _evidence(db_session, candidate, "affiliate_program_exists", True)
    first = _evidence(db_session, candidate, "commission_percent", 10, evidence_id="commission-ten")
    second = _evidence(db_session, candidate, "commission_percent", 15, evidence_id="commission-fifteen")

    brief = ContentBriefBuilderService(db_session).build(_request(requested_angle="ECONOMICS_REFERENCE"))
    economics = [point for point in brief.proof_points if point["usage_role"] == EvidenceUsageRole.ECONOMICS.value]
    assert {(point["evidence_observation_id"], point["observed_value"]) for point in economics} == {
        (first.id, 10),
        (second.id, 15),
    }

    db_session.rollback()
    _, candidate = _run_and_candidate(db_session, run_id="no-econ-run", candidate_id="no-econ-candidate")
    _evidence(db_session, candidate, "affiliate_program_exists", True)
    missing_economics = ContentBriefBuilderService(db_session).build(
        _request(discovery_run_id="no-econ-run", discovery_candidate_id="no-econ-candidate")
    )
    assert all(point["usage_role"] != EvidenceUsageRole.ECONOMICS.value for point in missing_economics.proof_points)


def test_angle_cta_and_keyword_defaults_are_deterministic(db_session):
    _, candidate = _run_and_candidate(db_session)
    _evidence(db_session, candidate, "affiliate_program_exists", True)
    builder = ContentBriefBuilderService(db_session)

    first = builder.build(_request(content_type=ContentType.BUYER_GUIDE.value, requested_cta="VISIT_OFFER"))
    assert first.angle == "BUYER_GUIDE"
    assert first.call_to_action == "CHECK_DETAILS"
    assert first.target_keywords == [
        "example offer buyer guide",
        "example partner program buyer guide",
        "example vendor buyer guide",
        "example vendor review",
        "example.com buyer guide",
    ]

    with pytest.raises(ValueError, match="OFFER_DETAILS requires"):
        builder.build(_request(requested_angle="OFFER_DETAILS"))


def test_repeated_build_reconciles_evidence_without_duplicate_links(db_session):
    _, candidate = _run_and_candidate(db_session)
    _evidence(db_session, candidate, "affiliate_program_exists", True, evidence_id="program-one")
    builder = ContentBriefBuilderService(db_session)

    first = builder.build(_request())
    repeated = builder.build(_request())
    assert repeated.id == first.id
    assert db_session.query(ContentBrief).count() == 1
    assert db_session.query(ContentBriefEvidence).count() == 1

    new_evidence = _evidence(db_session, candidate, "affiliate_network", "Impact", evidence_id="network-one")
    reconciled = builder.build(_request())
    assert reconciled.id == first.id
    assert db_session.query(ContentBriefEvidence).filter(
        ContentBriefEvidence.evidence_observation_id == new_evidence.id,
        ContentBriefEvidence.usage_role == EvidenceUsageRole.SUPPORTING.value,
    ).count() == 1
    assert db_session.query(ContentBriefEvidence).count() == 2


def test_service_rejects_cross_candidate_evidence_links(db_session):
    run, candidate = _run_and_candidate(db_session)
    _, other_candidate = _run_and_candidate(db_session, run_id="other-run", candidate_id="other-candidate")
    foreign_evidence = _evidence(db_session, other_candidate, "affiliate_program_exists", True)

    with pytest.raises(ValueError, match="provenance"):
        ContentBriefService(db_session).create_brief(
            discovery_run_id=run.id,
            discovery_candidate_id=candidate.id,
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Evidence boundary test.",
            evidence_links=[
                {
                    "evidence_observation_id": foreign_evidence.id,
                    "usage_role": EvidenceUsageRole.PRIMARY.value,
                }
            ],
        )


def test_builder_has_no_generation_asset_or_external_side_effects(db_session):
    _, candidate = _run_and_candidate(db_session)
    _evidence(db_session, candidate, "affiliate_program_exists", True)
    builder = ContentBriefBuilderService(db_session)

    with patch("requests.get", side_effect=AssertionError("network forbidden")), patch(
        "socket.create_connection", side_effect=AssertionError("network forbidden")
    ), patch("app.ai.provider_factory.ProviderFactory.create", side_effect=AssertionError("provider forbidden")):
        builder.build(_request())

    assert db_session.query(ContentGenerationRun).count() == 0
    assert db_session.query(Product).count() == 0
    assert db_session.query(AffiliateProgram).count() == 0
    assert db_session.query(AffiliateOpportunity).count() == 0
    assert db_session.query(AffiliateContentAsset).count() == 0
