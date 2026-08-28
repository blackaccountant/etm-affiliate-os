from datetime import timezone
from decimal import Decimal
import hashlib

import pytest

from app.discovery.adapters.base import DiscoveryEvidence
from app.discovery.adapters.official_site import _Claim
from app.discovery.adapters.base import DiscoveryAdapter
from app.discovery.adapters.official_site import OfficialSiteDiscoveryAdapter
from app.discovery.contracts import DiscoveryInputType, DiscoveryRunCreate, VerificationStatus
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.services.official_site_discovery_service import OfficialSiteDiscoveryService
from app.services.website_fetcher import FetchedWebsitePage
from app.services.website_research_service import ResearchPage, WebsiteResearchService


class FakeResearcher:
    """Injected page transport: default tests never need the internet."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def research_pages(self, url):
        self.calls.append(url)
        return self.pages


def page(url, content, status=200):
    return ResearchPage.from_content(url, content, status)


def adapter(pages):
    return OfficialSiteDiscoveryAdapter(FakeResearcher(pages))


def create_run(db_session):
    return DiscoveryRunRepository(db_session).create(
        DiscoveryRunCreate(input_type=DiscoveryInputType.URL, input_value="https://acme.example")
    )


@pytest.fixture(autouse=True)
def reject_network(monkeypatch):
    """The Phase 2 contract tests must use injected local collaborators only."""
    def fail_network(*args, **kwargs):
        raise AssertionError("network access is forbidden in Phase 2 contract tests")

    monkeypatch.setattr("httpx.get", fail_network)


def test_adapter_contract_page_provenance_and_typed_percent_candidate():
    researcher = FakeResearcher([
        page("https://acme.example/", "Welcome to Acme."),
        page(
            "https://acme.example/affiliate-program",
            "Join our affiliate program. Earn 30% commission. Our 90 day tracking cookie applies. Apply at https://join.acme.example/signup.",
        ),
    ])
    subject = OfficialSiteDiscoveryAdapter(researcher)
    assert isinstance(subject, DiscoveryAdapter)
    result = subject.discover("https://www.acme.example/products?x=1")
    assert result.candidate.canonical_domain == "acme.example"
    assert result.candidate.source_url == "https://acme.example/affiliate-program"
    assert result.candidate.affiliate_url == "https://join.acme.example/signup"
    assert result.candidate.commission_model.value == "PERCENT"
    assert result.candidate.commission_percent == Decimal("30.0")
    assert result.candidate.cookie_days == 90
    assert result.candidate.verification_status is VerificationStatus.VERIFIED
    claims = {item.claim_type: item for item in result.evidence}
    assert claims["affiliate_program_exists"].observed_value is True
    assert claims["commission_percent"].observed_value == 30
    assert claims["commission_percent"].source_url.endswith("affiliate-program")
    assert "30% commission" in claims["commission_percent"].excerpt
    assert claims["commission_percent"].content_hash == page("x", "Join our affiliate program. Earn 30% commission. Our 90 day tracking cookie applies. Apply at https://join.acme.example/signup.").content_hash
    assert (subject.extractor, subject.extractor_version) == ("official-site-parser", "2.0.0")
    assert researcher.calls == ["https://www.acme.example/products?x=1"]


def test_default_adapter_reuses_existing_website_research_service():
    assert isinstance(OfficialSiteDiscoveryAdapter().researcher, WebsiteResearchService)


def test_commission_semantics_cookie_network_and_unknowns_are_deterministic():
    recurring = adapter([page("https://acme.example/affiliate", "Become an affiliate. Earn 30% recurring commission through Impact Radius. 30-day cookie.")]).discover("https://acme.example")
    assert recurring.candidate.commission_model.value == "RECURRING_PERCENT"
    assert recurring.candidate.commission_percent == Decimal("30.0")
    assert recurring.candidate.recurring_period == "recurring"
    assert recurring.candidate.affiliate_network == "Impact"
    fixed = adapter([page("https://acme.example/affiliate", "Our affiliate program pays $100 commission per sale.")]).discover("https://acme.example")
    assert fixed.candidate.commission_model.value == "FIXED"
    assert fixed.candidate.commission_amount == Decimal("100.0")
    assert fixed.candidate.commission_currency is None
    cpa = adapter([page("https://acme.example/affiliate", "Join our affiliate program. CPA $50.")]).discover("https://acme.example")
    assert cpa.candidate.commission_model.value == "CPA"
    assert cpa.candidate.commission_amount == Decimal("50.0")
    unknown = adapter([page("https://acme.example/affiliate", "Join our affiliate program today.")]).discover("https://acme.example")
    assert unknown.candidate.commission_model.value == "UNKNOWN"
    assert unknown.candidate.commission_percent is None and unknown.candidate.cookie_days is None
    assert unknown.candidate.verification_status is VerificationStatus.PARTIAL


def test_conflicting_claims_are_retained_and_winner_is_deterministic():
    pages = [
        page("https://acme.example/affiliate-z", "Join our affiliate program. Earn 20% commission."),
        page("https://acme.example/affiliate-a", "Join our affiliate program. Earn 40% commission."),
    ]
    result = adapter(pages).discover("https://acme.example")
    amounts = [item.observed_value for item in result.evidence if item.claim_type == "commission_percent"]
    assert amounts == [40, 20]
    assert result.candidate.commission_percent == Decimal("40.0")


def test_ingestion_persists_once_and_recalculates_counters(db_session):
    pages = [page("https://acme.example/affiliate", "Join our affiliate program via CJ Affiliate. Earn 30% commission. Cookie window of 30 days.")]
    run = create_run(db_session)
    service = OfficialSiteDiscoveryService(db_session, adapter(pages))
    first = service.ingest(run.id, "https://acme.example")
    second = service.ingest(run.id, "https://acme.example")
    candidates = service.candidates.list_by_run(run.id)
    evidence = service.evidence.list_by_candidate(candidates[0].id)
    refreshed = service.runs.get_by_id(run.id)
    assert first is not None and second is not None
    assert len(candidates) == 1
    assert len(evidence) == len(first.evidence)
    assert {item.claim_type for item in evidence} >= {"affiliate_program_exists", "commission_percent", "cookie_days", "affiliate_network"}
    commission_evidence = next(item for item in evidence if item.claim_type == "commission_percent")
    assert commission_evidence.source_url == "https://acme.example/affiliate"
    assert commission_evidence.excerpt and commission_evidence.http_status == 200
    assert commission_evidence.content_hash and commission_evidence.confidence == 95
    assert (commission_evidence.extractor, commission_evidence.extractor_version) == ("official-site-parser", "2.0.0")
    assert refreshed.candidate_count == 1 and refreshed.verified_count == 1 and refreshed.selected_count == 0
    assert db_session.query(Product).count() == 0


def test_source_url_and_verified_status_follow_supporting_program_page():
    result = adapter([
        page("https://acme.example/affiliate", "Contact information only."),
        page("https://acme.example/partners/program", "Join our affiliate program. Earn 30% commission."),
    ]).discover("https://acme.example")
    assert result.candidate.source_url == "https://acme.example/partners/program"
    assert result.candidate.verification_status is VerificationStatus.VERIFIED
    assert result.candidate.disposition.value == "VERIFIED"


def test_unrelated_confirmation_is_partial_until_same_page_confirmation_exists():
    partial = adapter([
        page("https://acme.example/affiliate", "Join our affiliate program."),
        page("https://acme.example/pricing", "Earn 30% commission. Cookie window of 30 days."),
    ]).discover("https://acme.example")
    assert partial.candidate.source_url == "https://acme.example/affiliate"
    assert partial.candidate.verification_status is VerificationStatus.PARTIAL
    assert partial.candidate.disposition.value == "DISCOVERED"
    verified = adapter([
        page("https://acme.example/affiliate", "Join our affiliate program. Earn 30% commission."),
    ]).discover("https://acme.example")
    assert verified.candidate.verification_status is VerificationStatus.VERIFIED
    assert verified.candidate.disposition.value == "VERIFIED"


def test_http_timestamp_hash_evidence_and_legacy_research_provenance():
    content = "Join our affiliate program. Earn 30% commission. Cookie window of 30 days via Impact. Apply at https://join.acme.example."
    observed = page("https://acme.example/affiliate", content, status=201)
    result = adapter([observed]).discover("https://acme.example")
    claims = {item.claim_type: item for item in result.evidence}
    assert observed.fetched_at.tzinfo is timezone.utc
    assert observed.content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    for claim_type in {"affiliate_program_exists", "commission_model", "commission_percent", "cookie_days", "affiliate_network", "affiliate_url"}:
        claim = claims[claim_type]
        assert claim.source_url == observed.url and claim.http_status == 201
        assert claim.excerpt and claim.content_hash == observed.content_hash and claim.confidence > 0
    assert (result.candidate.source_adapter, result.candidate.source_type) == ("official_site", "official_site")

    class FakeFetcher:
        def fetch(self, url):
            return "<html><body>Legacy page</body></html>"

    researcher = WebsiteResearchService(fetcher=FakeFetcher())
    researcher.MAX_PAGES = 1
    assert researcher.research("https://acme.example") == "SOURCE URL:\nhttps://acme.example\n\nCONTENT:\nLegacy page"

    class FakeMetadataFetcher:
        def fetch_with_metadata(self, url):
            return FetchedWebsitePage("<html><body>Observed page</body></html>", 206)

    provenance_researcher = WebsiteResearchService(fetcher=FakeMetadataFetcher())
    provenance_researcher.MAX_PAGES = 1
    assert provenance_researcher.research_pages("https://acme.example")[0].http_status == 206


@pytest.mark.parametrize(
    ("text", "model", "amount", "currency"),
    [
        ("Join our affiliate program. USD 100 commission per sale.", "FIXED", "100", "USD"),
        ("Join our affiliate program. CPA USD 50.", "CPA", "50", "USD"),
        ("Join our affiliate program. $100 commission per sale.", "FIXED", "100", None),
    ],
)
def test_currency_normalization_never_infers_from_dollar_symbol(text, model, amount, currency):
    result = adapter([page("https://acme.example/affiliate", text)]).discover("https://acme.example")
    assert result.candidate.commission_model.value == model
    assert result.candidate.commission_amount == Decimal(amount)
    assert result.candidate.commission_currency == currency


@pytest.mark.parametrize(
    ("alias", "normalized"),
    [
        ("Impact", "Impact"), ("impact.com", "Impact"), ("Impact Radius", "Impact"),
        ("PartnerStack", "PartnerStack"), ("CJ Affiliate", "CJ"), ("Commission Junction", "CJ"),
        ("ShareASale", "ShareASale"), ("Awin", "Awin"),
        ("Rakuten Advertising", "Rakuten"), ("Rakuten", "Rakuten"),
    ],
)
def test_network_aliases_only_normalize_official_site_text(alias, normalized):
    result = adapter([page("https://acme.example/affiliate", f"Join our affiliate program through {alias}.")]).discover("https://acme.example")
    assert result.candidate.affiliate_network == normalized


def test_claim_selection_prefers_confidence_then_explicit_page_and_keeps_losers():
    low_generic = _Claim(DiscoveryEvidence("cookie_days", 30, "https://acme.example/pricing", "30 days", 200, "a", 60), 0)
    high_generic = _Claim(DiscoveryEvidence("cookie_days", 60, "https://acme.example/pricing", "60 days", 200, "b", 90), 0)
    tied_affiliate = _Claim(DiscoveryEvidence("cookie_days", 90, "https://acme.example/affiliate", "90 days", 200, "c", 90), 2)
    selected = OfficialSiteDiscoveryAdapter._select([low_generic, high_generic, tied_affiliate])
    assert selected["cookie_days"] is tied_affiliate
    assert [claim.evidence.observed_value for claim in (low_generic, high_generic, tied_affiliate)] == [30, 60, 90]


def test_identity_no_evidence_and_missing_run_are_safe(db_session):
    source = "https://www.acme.example/path"
    first = adapter([page("https://acme.example/affiliate", "Join our affiliate program. Earn 30% commission.")]).discover(source)
    second = adapter([page("https://acme.example/affiliate", "Join our affiliate program. Earn 30% commission.")]).discover(source)
    assert first.candidate.program_identity_key == second.candidate.program_identity_key
    assert first.candidate.dedupe_key == second.candidate.dedupe_key
    assert adapter([page("https://acme.example/", "General company information.")]).discover(source) is None
    assert adapter([page("https://acme.example/", "Our affiliate links are disclosed here.")]).discover(source) is None
    service = OfficialSiteDiscoveryService(db_session, adapter([page("https://acme.example/affiliate", "Join our affiliate program.")]))
    with pytest.raises(ValueError, match="discovery run does not exist"):
        service.ingest("missing-run", source)
    assert service.candidates.list_by_run("missing-run") == []


def test_distinct_conflicts_persist_once_and_counters_reflect_verified_and_partial(db_session):
    run = create_run(db_session)
    verified = OfficialSiteDiscoveryService(db_session, adapter([
        page("https://acme.example/affiliate-a", "Join our affiliate program through CJ Affiliate. Earn 20% commission."),
        page("https://acme.example/affiliate-b", "Join our affiliate program through CJ Affiliate. Earn 40% commission."),
    ]))
    verified.ingest(run.id, "https://acme.example")
    verified.ingest(run.id, "https://acme.example")
    partial = OfficialSiteDiscoveryService(db_session, adapter([
        page("https://acme.example/", "PartnerStack is used for partner resources."),
    ]))
    partial.ingest(run.id, "https://acme.example")
    candidates = verified.candidates.list_by_run(run.id)
    first_evidence = verified.evidence.list_by_candidate(candidates[0].id)
    run = verified.runs.get_by_id(run.id)
    assert len([item for item in first_evidence if item.claim_type == "commission_percent"]) == 2
    assert len(candidates) == 2
    assert (run.candidate_count, run.verified_count, run.selected_count) == (2, 1, 0)
    assert db_session.query(Product).count() == 0
    assert db_session.query(AffiliateProgram).count() == 0
