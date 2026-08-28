from decimal import Decimal

from app.discovery.adapters.base import DiscoveryAdapter
from app.discovery.adapters.official_site import OfficialSiteDiscoveryAdapter
from app.discovery.contracts import DiscoveryInputType, DiscoveryRunCreate, VerificationStatus
from app.models.product import Product
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.services.official_site_discovery_service import OfficialSiteDiscoveryService
from app.services.website_research_service import ResearchPage


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
    assert refreshed.candidate_count == 1 and refreshed.verified_count == 1 and refreshed.selected_count == 0
    assert db_session.query(Product).count() == 0
