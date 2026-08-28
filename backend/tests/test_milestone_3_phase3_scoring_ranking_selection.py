from decimal import Decimal

import pytest

from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, DiscoveryInputType, DiscoveryRunCreate, EvidenceObservationCreate, VerificationStatus
from app.intelligence.scoring import AffiliateScoringEngine
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.services.discovery_candidate_scoring_service import DiscoveryCandidateScoringService, DiscoveryRankingService, DiscoveryWinnerSelectionService
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product


def create_run(db_session):
    return DiscoveryRunRepository(db_session).create(
        DiscoveryRunCreate(input_type=DiscoveryInputType.URL, input_value="https://acme.example")
    )


def create_candidate(db_session, run_id, name, **overrides):
    defaults = {
        "source_adapter": "official_site", "source_type": "official_site",
        "source_url": f"https://{name}.example/affiliate", "canonical_domain": f"{name}.example",
        "program_identity_key": f"program:{name}", "dedupe_key": f"candidate:{name}",
        "commission_model": CommissionModel.PERCENT, "commission_percent": Decimal("20"),
        "verification_status": VerificationStatus.VERIFIED, "disposition": CandidateDisposition.VERIFIED,
        "confidence": 80,
    }
    defaults.update(overrides)
    return DiscoveryCandidateRepository(db_session).create(run_id, DiscoveryCandidateCreate(**defaults))


def add_evidence(db_session, candidate, suffix="one"):
    return EvidenceObservationRepository(db_session).create(EvidenceObservationCreate(
        candidate_id=candidate.id, claim_type="commission_percent", observed_value=20,
        source_url=f"https://{candidate.canonical_domain}/{suffix}", source_type="official_site",
        excerpt=f"Evidence {suffix}", http_status=200, content_hash=f"hash-{suffix}",
        extractor="test", extractor_version="1", confidence=90,
    ))


@pytest.mark.parametrize(
    ("status", "model", "percent", "amount", "expected"),
    [
        (VerificationStatus.VERIFIED, CommissionModel.RECURRING_PERCENT, Decimal("30"), None, (True, "Yes", "Recurring Percentage", "30% recurring")),
        (VerificationStatus.PARTIAL, CommissionModel.PERCENT, Decimal("20"), None, (False, "Likely", "Percentage", "20%")),
        (VerificationStatus.UNVERIFIED, CommissionModel.FIXED, None, Decimal("100"), (False, "Unknown", "FIXED", "100")),
        (VerificationStatus.STALE, CommissionModel.UNKNOWN, None, None, (False, "Unknown", "Unknown", "Unknown")),
    ],
)
def test_typed_bridge_maps_verification_and_economics(db_session, status, model, percent, amount, expected):
    run = create_run(db_session)
    candidate = create_candidate(db_session, run.id, f"bridge-{status.value}-{model.value}", verification_status=status, commission_model=model, commission_percent=percent, commission_amount=amount, cookie_days=90, affiliate_network="Impact")
    add_evidence(db_session, candidate)
    discovery = DiscoveryCandidateScoringService(db_session).to_legacy_discovery(candidate, EvidenceObservationRepository(db_session).list_by_candidate(candidate.id))
    assert (discovery["affiliate_program_found"], discovery["affiliate_program_likely"], discovery["commission_type"], discovery["commission_estimate"]) == expected
    assert discovery["cookie_window"] == "90 days" and discovery["affiliate_platform"] == "Impact"
    assert discovery["evidence"] == ["Evidence one"]


def test_scoring_persists_engine_result_without_overwriting_evidence_confidence(db_session):
    run = create_run(db_session)
    candidate = create_candidate(db_session, run.id, "scored", commission_model=CommissionModel.RECURRING_PERCENT, commission_percent=Decimal("30"), cookie_days=180, affiliate_network="Impact", confidence=91)
    add_evidence(db_session, candidate)
    service = DiscoveryCandidateScoringService(db_session)
    first = service.score_candidate(candidate.id)
    second = service.score_candidate(candidate.id)
    assert first.id == second.id and second.confidence == 91 and second.score == first.score
    assert second.score_breakdown["basis"] == "affiliate_economics_only"
    assert second.score_breakdown["commercial_enrichment_applied"] is False
    assert second.score_breakdown["engine_confidence"] != second.confidence
    assert second.score_breakdown["grade"] and second.score_reasons
    assert all(isinstance(reason, dict) for reason in second.score_reasons)
    assert len(DiscoveryCandidateRepository(db_session).list_by_run(run.id)) == 1
    assert len(EvidenceObservationRepository(db_session).list_by_candidate(candidate.id)) == 1


def test_confidence_bonus_regression_for_two_and_four_discovery_reasons():
    engine = AffiliateScoringEngine()
    analysis = AffiliateAnalysis(company="x", website="https://x.example", category="", summary="", target_audience=[], pricing_model="", recommendation="")
    two = engine.score(analysis, {"affiliate_program_found": True, "commission_type": "Percentage", "commission_estimate": "20%", "cookie_window": "Unknown", "affiliate_platform": "Unknown", "confidence": 80})
    four = engine.score(analysis, {"affiliate_program_found": True, "commission_type": "Recurring Percentage", "commission_estimate": "20% recurring", "cookie_window": "180 days", "affiliate_platform": "Impact", "confidence": 80})
    assert two.confidence == 60
    assert four.confidence == 65


def test_ranking_is_verified_first_and_uses_all_deterministic_tiebreakers(db_session):
    run = create_run(db_session)
    verified_low = create_candidate(db_session, run.id, "verified-low", confidence=70)
    partial_high = create_candidate(db_session, run.id, "partial-high", verification_status=VerificationStatus.PARTIAL, disposition=CandidateDisposition.DISCOVERED, confidence=99)
    score_high = create_candidate(db_session, run.id, "score-high", confidence=80)
    percent_high = create_candidate(db_session, run.id, "percent-high", confidence=80, commission_percent=Decimal("30"))
    cookie_high = create_candidate(db_session, run.id, "cookie-high", confidence=80, commission_percent=Decimal("30"), cookie_days=90)
    evidence_high = create_candidate(db_session, run.id, "evidence-high", confidence=80, commission_percent=Decimal("30"), cookie_days=90)
    identity_a = create_candidate(db_session, run.id, "identity-a", confidence=80, commission_percent=Decimal("30"), cookie_days=90)
    identity_b = create_candidate(db_session, run.id, "identity-b", confidence=80, commission_percent=Decimal("30"), cookie_days=90)
    for candidate, score in [(verified_low, 60), (partial_high, 90), (score_high, 85), (percent_high, 80), (cookie_high, 80), (evidence_high, 80), (identity_a, 80), (identity_b, 80)]:
        DiscoveryCandidateRepository(db_session).save_score(candidate.id, score, {}, [])
        add_evidence(db_session, candidate)
    add_evidence(db_session, evidence_high, "two")
    ranked = DiscoveryRankingService(db_session).rank(run.id)
    ids = [item.candidate.id for item in ranked]
    assert ids.index(verified_low.id) < ids.index(partial_high.id)
    assert ids.index(score_high.id) < ids.index(percent_high.id)
    assert ids.index(cookie_high.id) < ids.index(percent_high.id)
    assert ids.index(evidence_high.id) < ids.index(cookie_high.id)
    assert ids.index(evidence_high.id) < ids.index(identity_a.id) < ids.index(identity_b.id)
    assert ids == [item.candidate.id for item in DiscoveryRankingService(db_session).rank(run.id)]


def test_selection_thresholds_top_n_rejection_and_counter_recomputation(db_session):
    run = create_run(db_session)
    first = create_candidate(db_session, run.id, "winner-one", confidence=80)
    second = create_candidate(db_session, run.id, "winner-two", confidence=75)
    partial = create_candidate(db_session, run.id, "partial", verification_status=VerificationStatus.PARTIAL, disposition=CandidateDisposition.DISCOVERED, confidence=99)
    rejected = create_candidate(db_session, run.id, "rejected", confidence=99)
    low_confidence = create_candidate(db_session, run.id, "low-confidence", confidence=69)
    for candidate, score in [(first, 80), (second, 70), (partial, 99), (rejected, 99), (low_confidence, 99)]:
        DiscoveryCandidateRepository(db_session).save_score(candidate.id, score, {}, [])
        add_evidence(db_session, candidate)
    DiscoveryCandidateRepository(db_session).set_disposition(rejected.id, CandidateDisposition.REJECTED)
    selection = DiscoveryWinnerSelectionService(db_session)
    result = selection.apply_selection(run.id, top_n=2)
    assert result.selected_ids == (first.id, second.id)
    again = selection.apply_selection(run.id, top_n=2)
    assert again.selected_ids == result.selected_ids
    candidates = {candidate.id: candidate for candidate in DiscoveryCandidateRepository(db_session).list_by_run(run.id)}
    refreshed_run = DiscoveryRunRepository(db_session).get_by_id(run.id)
    assert candidates[first.id].disposition == CandidateDisposition.SELECTED.value
    assert candidates[second.id].disposition == CandidateDisposition.SELECTED.value
    assert candidates[partial.id].disposition == CandidateDisposition.DISCOVERED.value
    assert candidates[rejected.id].disposition == CandidateDisposition.REJECTED.value
    assert (refreshed_run.candidate_count, refreshed_run.verified_count, refreshed_run.selected_count) == (5, 4, 2)
    assert db_session.query(Product).count() == 0 and db_session.query(AffiliateProgram).count() == 0


def test_selection_none_and_rollback_leave_no_partial_winners(db_session, monkeypatch):
    run = create_run(db_session)
    candidate = create_candidate(db_session, run.id, "rollback", confidence=80)
    DiscoveryCandidateRepository(db_session).save_score(candidate.id, 80, {}, [])
    selection = DiscoveryWinnerSelectionService(db_session)
    def fail_flush():
        raise RuntimeError("selection write failed")
    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="selection write failed"):
        selection.apply_selection(run.id)
    candidate = DiscoveryCandidateRepository(db_session).get_by_id(candidate.id)
    assert candidate.disposition == CandidateDisposition.VERIFIED.value
    monkeypatch.undo()
    DiscoveryCandidateRepository(db_session).save_score(candidate.id, 39, {}, [])
    assert selection.apply_selection(run.id).selected_ids == ()
