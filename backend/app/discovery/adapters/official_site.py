"""Deterministic official-company-site affiliate discovery."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Protocol
from urllib.parse import urlparse

from app.discovery.adapters.base import AdapterDiscoveryResult, DiscoveryEvidence
from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, VerificationStatus
from app.discovery.identity import candidate_dedupe_key, canonical_domain, program_identity_key
from app.services.website_research_service import ResearchPage, WebsiteResearchService


class PageResearcher(Protocol):
    def research_pages(self, url: str) -> list[ResearchPage]: ...


@dataclass(frozen=True)
class _Claim:
    evidence: DiscoveryEvidence
    page_priority: int


class OfficialSiteDiscoveryAdapter:
    """Extract normalized affiliate claims from injected official-site pages.

    A claim wins by confidence, then affiliate-page specificity, then URL/excerpt
    lexical order. Every extracted claim remains available as evidence.
    """

    name = "official_site"
    source_type = "official_site"
    extractor = "official-site-parser"
    extractor_version = "2.0.0"

    _NETWORKS = (
        ("Impact", ("impact radius", "impact.com", "impact")),
        ("PartnerStack", ("partnerstack",)),
        ("CJ", ("cj affiliate", "commission junction")),
        ("ShareASale", ("shareasale",)),
        ("Awin", ("awin",)),
        ("Rakuten", ("rakuten advertising", "rakuten")),
    )
    _STRONG = ("affiliate program", "become an affiliate", "join our affiliate", "affiliate application", "affiliate partners")

    def __init__(self, researcher: PageResearcher | None = None):
        self.researcher = researcher or WebsiteResearchService()

    def discover(self, source: str) -> AdapterDiscoveryResult | None:
        domain = canonical_domain(source)
        parsed = urlparse(source if "://" in source else f"https://{source}")
        if not domain or parsed.scheme not in {"http", "https"}:
            raise ValueError("official-site discovery requires a valid http(s) URL")
        pages = sorted(self.researcher.research_pages(source), key=lambda page: page.url)
        claims = [claim for page in pages for claim in self._extract_page(page)]
        if not claims:
            return None
        selected = self._select(claims)
        values = {key: claim.evidence.observed_value for key, claim in selected.items()}
        best_page = max(pages, key=lambda page: (self._page_priority(page.url), page.url))
        explicit_page = self._page_priority(best_page.url) > 0
        extra = any(key in values for key in ("commission_percent", "commission_amount", "cookie_days", "affiliate_network", "affiliate_url"))
        verified = bool(values.get("affiliate_program_exists")) and explicit_page and extra
        status = VerificationStatus.VERIFIED if verified else VerificationStatus.PARTIAL
        confidence = max(claim.evidence.confidence for claim in selected.values())
        network = values.get("affiliate_network")
        program_key = program_identity_key(domain, network, None)
        candidate = DiscoveryCandidateCreate(
            source_adapter=self.name,
            source_type=self.source_type,
            source_url=best_page.url if explicit_page else source,
            canonical_domain=domain,
            affiliate_network=network,
            affiliate_url=values.get("affiliate_url"),
            program_identity_key=program_key,
            dedupe_key=candidate_dedupe_key(program_key),
            commission_model=CommissionModel(values.get("commission_model", CommissionModel.UNKNOWN.value)),
            commission_percent=self._decimal(values.get("commission_percent")),
            commission_amount=self._decimal(values.get("commission_amount")),
            commission_currency=values.get("commission_currency"),
            recurring_period=values.get("recurring_period"),
            cookie_days=values.get("cookie_days"),
            verification_status=status,
            disposition=CandidateDisposition.VERIFIED if verified else CandidateDisposition.DISCOVERED,
            confidence=confidence,
        )
        return AdapterDiscoveryResult(candidate=candidate, evidence=tuple(item.evidence for item in claims))

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _page_priority(url: str) -> int:
        path = urlparse(url).path.lower()
        return 2 if "affiliate" in path else 1 if any(word in path for word in ("partner", "referral")) else 0

    def _claim(self, page: ResearchPage, claim_type: str, value: object, excerpt: str, confidence: int) -> _Claim:
        return _Claim(DiscoveryEvidence(claim_type, value, page.url, excerpt[:500], page.http_status, page.content_hash, confidence), self._page_priority(page.url))

    def _extract_page(self, page: ResearchPage) -> list[_Claim]:
        text = " ".join(page.content.split())
        lowered = text.lower()
        claims: list[_Claim] = []
        strong = next((term for term in self._STRONG if term in lowered), None)
        if strong:
            claims.append(self._claim(page, "affiliate_program_exists", True, self._excerpt(text, strong), 90 + 5 * bool(self._page_priority(page.url))))
        for network, variants in self._NETWORKS:
            variant = next((item for item in variants if item in lowered), None)
            if variant:
                claims.append(self._claim(page, "affiliate_network", network, self._excerpt(text, variant), 85))
                break
        cookie = re.search(r"(?:([0-9]+)[- ]day (?:tracking )?cookie|cookie window of ([0-9]+) days|cookie.{0,30}?([0-9]+) days)", lowered)
        if cookie:
            claims.append(self._claim(page, "cookie_days", int(next(value for value in cookie.groups() if value)), cookie.group(0), 90))
        commission = self._commission(lowered)
        if commission:
            model, amount, percent, excerpt = commission
            claims.append(self._claim(page, "commission_model", model.value, excerpt, 95))
            if percent is not None:
                claims.append(self._claim(page, "commission_percent", float(percent), excerpt, 95))
            if amount is not None:
                claims.append(self._claim(page, "commission_amount", float(amount), excerpt, 95))
            currency = self._currency(excerpt)
            if currency:
                claims.append(self._claim(page, "commission_currency", currency, excerpt, 90))
            if model is CommissionModel.RECURRING_PERCENT:
                claims.append(self._claim(page, "recurring_period", "recurring", excerpt, 90))
        url = re.search(r"https?://[^\s)]+", text)
        if url and any(word in lowered for word in ("apply", "join", "affiliate")):
            claims.append(self._claim(page, "affiliate_url", url.group(0).rstrip(".,"), self._excerpt(text, url.group(0)), 85))
        return claims

    @staticmethod
    def _commission(text: str):
        recurring = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s+(?:recurring\s+)?commission", text)
        if recurring:
            model = CommissionModel.RECURRING_PERCENT if "recurring" in recurring.group(0) else CommissionModel.PERCENT
            return model, None, Decimal(recurring.group(1)), recurring.group(0)
        cpa = re.search(r"\bcpa\s+(?:([A-Z]{3})\s*)?[$]?([0-9]+(?:\.[0-9]+)?)", text, re.I)
        if cpa:
            return CommissionModel.CPA, Decimal(cpa.group(2)), None, cpa.group(0)
        fixed = re.search(r"(?:([A-Z]{3})\s*)?[$]([0-9]+(?:\.[0-9]+)?)\s+commission per sale", text, re.I)
        if fixed:
            return CommissionModel.FIXED, Decimal(fixed.group(2)), None, fixed.group(0)
        return None

    @staticmethod
    def _currency(excerpt: str) -> str | None:
        match = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", excerpt, re.I)
        return match.group(1).upper() if match else None

    @staticmethod
    def _excerpt(text: str, needle: str) -> str:
        start = max(0, text.lower().find(needle.lower()) - 120)
        return text[start : start + 500]

    @staticmethod
    def _select(claims: list[_Claim]) -> dict[str, _Claim]:
        selected: dict[str, _Claim] = {}
        for claim in claims:
            current = selected.get(claim.evidence.claim_type)
            if current is None or (-claim.evidence.confidence, -claim.page_priority, claim.evidence.source_url, claim.evidence.excerpt) < (-current.evidence.confidence, -current.page_priority, current.evidence.source_url, current.evidence.excerpt):
                selected[claim.evidence.claim_type] = claim
        return selected
