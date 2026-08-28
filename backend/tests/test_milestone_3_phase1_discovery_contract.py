from datetime import timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.discovery.contracts import (
    CandidateDisposition,
    CommissionModel,
    DiscoveryCandidateCreate,
    DiscoveryInputType,
    DiscoveryRunCreate,
    DiscoveryRunStatus,
    EvidenceObservationCreate,
    VerificationStatus,
)
from app.discovery.identity import canonical_domain, candidate_dedupe_key, program_identity_key
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository


def candidate_payload(offer_name="Shared Hosting"):
    domain = canonical_domain("https://www.Hostinger.com/pricing?ref=x")
    program_key = program_identity_key(domain, "Impact", "Hostinger Affiliates")
    return DiscoveryCandidateCreate(
        source_adapter="official_site",
        source_type="website",
        source_url="https://hostinger.com/affiliates",
        vendor_name="Hostinger",
        canonical_domain=domain,
        offer_name=offer_name,
        program_name="Hostinger Affiliates",
        affiliate_network="Impact",
        affiliate_url="https://impact.com/hostinger",
        program_identity_key=program_key,
        dedupe_key=candidate_dedupe_key(program_key, offer_name),
        commission_model=CommissionModel.RECURRING_PERCENT,
        commission_percent=Decimal("30.00"),
        commission_amount=Decimal("12.50"),
        commission_currency="usd",
        recurring_period="monthly",
        cookie_days=30,
        payout_threshold=Decimal("25.00"),
        payout_currency="eur",
        verification_status=VerificationStatus.PARTIAL,
        disposition=CandidateDisposition.DISCOVERED,
        confidence=75,
        score=82,
        score_breakdown={"commercial": 50, "evidence": 32},
        score_reasons=[{"title": "Commission evidence", "points": 32}],
    )


def create_run(repository, key=None):
    return repository.create(
        DiscoveryRunCreate(
            input_type=DiscoveryInputType.NICHE,
            input_value="web hosting",
            input_data={"regions": ["EU", "US"], "limit": 10},
            idempotency_key=key,
        )
    )


def test_canonical_domain_discards_url_presentation():
    assert canonical_domain("https://www.Hostinger.com/") == "hostinger.com"
    assert canonical_domain("https://user:pass@hostinger.com:8443/pricing?ref=x#top") == "hostinger.com"
    assert canonical_domain("HOSTINGER.COM.") == "hostinger.com"
    assert canonical_domain("not a valid host") == ""


def test_program_and_candidate_identity_are_deterministic_and_offer_specific():
    first = program_identity_key("https://www.hostinger.com/", "Impact", "Hostinger Affiliates")
    second = program_identity_key("HOSTINGER.COM", "impact", " hostinger   affiliates ")
    assert first == second
    assert candidate_dedupe_key(first, "Shared Hosting") == candidate_dedupe_key(second, " shared  hosting ")
    assert candidate_dedupe_key(first, "VPS Hosting") != candidate_dedupe_key(first, "Shared Hosting")
    assert program_identity_key("hostinger.com") == program_identity_key("hostinger.com", None, None)


def test_run_persists_idempotently_with_aware_utc_timestamps(db_session):
    repository = DiscoveryRunRepository(db_session)
    first = create_run(repository, "discovery-run-1")
    second = create_run(repository, "discovery-run-1")
    assert first.id == second.id
    assert first.input_data == {"limit": 10, "regions": ["EU", "US"]}
    assert first.status == DiscoveryRunStatus.CREATED.value
    assert first.created_at.tzinfo == timezone.utc
    assert first.updated_at.tzinfo == timezone.utc


def test_run_status_and_counter_persistence(db_session):
    repository = DiscoveryRunRepository(db_session)
    run = create_run(repository)
    updated = repository.update_counters(run.id, candidate_count=3, verified_count=2, selected_count=1)
    completed = repository.update_status(run.id, DiscoveryRunStatus.COMPLETED)
    assert (updated.candidate_count, updated.verified_count, updated.selected_count) == (3, 2, 1)
    assert completed.status == DiscoveryRunStatus.COMPLETED.value
    assert completed.completed_at.tzinfo == timezone.utc


def test_candidate_is_run_scoped_and_persists_typed_economics(db_session):
    runs = DiscoveryRunRepository(db_session)
    candidates = DiscoveryCandidateRepository(db_session)
    first_run, second_run = create_run(runs), create_run(runs)
    payload = candidate_payload()
    first = candidates.upsert_or_return_existing(first_run.id, payload)
    duplicate = candidates.upsert_or_return_existing(first_run.id, payload)
    later_run = candidates.upsert_or_return_existing(second_run.id, payload)
    assert first.id == duplicate.id
    assert first.id != later_run.id
    assert len(candidates.list_by_run(first_run.id)) == 1
    assert first.commission_percent == Decimal("30.00")
    assert first.commission_amount == Decimal("12.50")
    assert first.commission_currency == "USD"
    assert first.payout_currency == "EUR"
    assert first.disposition == CandidateDisposition.DISCOVERED.value
    assert first.verification_status == VerificationStatus.PARTIAL.value
    assert first.score_breakdown == {"commercial": 50, "evidence": 32}
    assert first.score_reasons == [{"points": 32, "title": "Commission evidence"}]
    assert first.created_at.tzinfo == timezone.utc


def test_missing_economics_remain_null(db_session):
    run = create_run(DiscoveryRunRepository(db_session))
    payload = candidate_payload()
    payload = payload.model_copy(update={
        "commission_model": CommissionModel.UNKNOWN,
        "commission_percent": None,
        "commission_amount": None,
        "commission_currency": None,
        "cookie_days": None,
        "payout_threshold": None,
        "payout_currency": None,
    })
    candidate = DiscoveryCandidateRepository(db_session).create(run.id, payload)
    assert candidate.commission_model == CommissionModel.UNKNOWN.value
    assert candidate.commission_percent is None and candidate.commission_amount is None
    assert candidate.cookie_days is None and candidate.payout_threshold is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("commission_percent", 101), ("confidence", -1), ("score", 101), ("cookie_days", -1), ("payout_threshold", -1)],
)
def test_economic_and_score_bounds_are_validated(field, value):
    with pytest.raises(ValidationError):
        DiscoveryCandidateCreate(
            **{
                **candidate_payload().model_dump(),
                field: value,
            }
        )


def test_evidence_is_field_specific_and_retains_structured_provenance(db_session):
    run = create_run(DiscoveryRunRepository(db_session))
    candidate = DiscoveryCandidateRepository(db_session).create(run.id, candidate_payload())
    repository = EvidenceObservationRepository(db_session)
    evidence = repository.create(
        EvidenceObservationCreate(
            candidate_id=candidate.id,
            claim_type="commission_percent",
            observed_value={"value": 30, "unit": "percent"},
            source_url="https://hostinger.com/affiliates",
            source_type="official_website",
            excerpt="Earn a 30% recurring commission.",
            http_status=200,
            content_hash="sha256:abc",
            extractor="official-site-parser",
            extractor_version="1.0.0",
            confidence=95,
        )
    )
    assert repository.list_by_candidate(candidate.id) == [evidence]
    assert repository.list_by_candidate_and_claim(candidate.id, "commission_percent") == [evidence]
    assert evidence.observed_value == {"unit": "percent", "value": 30}
    assert evidence.source_url == "https://hostinger.com/affiliates"
    assert (evidence.extractor, evidence.extractor_version) == ("official-site-parser", "1.0.0")
    assert evidence.observed_at.tzinfo == timezone.utc
