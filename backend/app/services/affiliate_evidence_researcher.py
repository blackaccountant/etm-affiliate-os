"""
Affiliate Evidence Researcher

Finds additional affiliate/referral/partner evidence from
the company's official website.

This service does NOT decide whether a company is a good
affiliate opportunity.

It only gathers evidence that can be passed to the AI
research layer.

Evidence hierarchy:

1. Official affiliate pages
2. Official referral pages
3. Official partner pages
4. Official commission/payout information

The service deliberately avoids treating generic partnerships,
reseller programs, integrations, or marketplaces as affiliate
evidence.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from app.services.content_extractor import ContentExtractor
from app.services.website_fetcher import WebsiteFetcher


class AffiliateEvidenceResearcher:
    """
    Searches the official company website for affiliate,
    referral, partner, and commission evidence.
    """

    SEARCH_PATHS = [
        "/affiliate",
        "/affiliates",
        "/affiliate-program",
        "/affiliate-programs",
        "/partners",
        "/partner",
        "/partner-program",
        "/partner-programs",
        "/referral",
        "/referrals",
        "/referral-program",
        "/referral-programs",
        "/commission",
    ]

    KEYWORDS = [
        "affiliate program",
        "affiliate",
        "affiliate commission",
        "affiliate partner",
        "referral program",
        "referral partner",
        "partner commission",
        "commission",
        "payout",
        "revenue share",
    ]

    def __init__(self):
        self.fetcher = WebsiteFetcher()
        self.extractor = ContentExtractor()

    # =========================================================
    # DOMAIN
    # =========================================================

    @staticmethod
    def _base_url(url: str) -> str:
        """
        Return the canonical scheme + hostname.
        """

        parsed = urlsplit(url)

        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"Invalid website URL: {url}"
            )

        return (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
        )

    # =========================================================
    # KEYWORD MATCHING
    # =========================================================

    @classmethod
    def _contains_evidence(
        cls,
        text: str,
    ) -> bool:
        """
        Determine whether extracted page content contains
        relevant affiliate/referral evidence keywords.
        """

        if not text:
            return False

        normalized = text.lower()

        return any(
            keyword in normalized
            for keyword in cls.KEYWORDS
        )

    # =========================================================
    # FETCH PAGE
    # =========================================================

    def _research_page(
        self,
        url: str,
    ) -> dict | None:
        """
        Fetch and extract one candidate evidence page.
        """

        try:

            html = self.fetcher.fetch(url)

            if not html:
                return None

            text = self.extractor.extract(html)

            if not text:
                return None

            if not self._contains_evidence(text):
                return None

            return {
                "url": url,
                "content": text[:8000],
            }

        except Exception:
            return None

    # =========================================================
    # MAIN RESEARCH
    # =========================================================

    def research(
        self,
        website_url: str,
    ) -> dict:
        """
        Search the official website for affiliate evidence.

        Returns a structured research result.
        """

        base_url = self._base_url(
            website_url
        )

        evidence_pages = []

        checked_urls = set()

        for path in self.SEARCH_PATHS:

            candidate_url = urljoin(
                base_url + "/",
                path.lstrip("/"),
            )

            if candidate_url in checked_urls:
                continue

            checked_urls.add(candidate_url)

            result = self._research_page(
                candidate_url
            )

            if result:

                evidence_pages.append(
                    result
                )

        # -----------------------------------------------------
        # Build combined evidence
        # -----------------------------------------------------

        if not evidence_pages:

            return {
                "found": False,
                "source": "official_website",
                "pages": [],
                "evidence": "",
                "message": (
                    "No explicit affiliate, referral, "
                    "commission, or affiliate-partner "
                    "evidence was found on the checked "
                    "official website paths."
                ),
            }

        evidence_parts = []

        for page in evidence_pages:

            evidence_parts.append(
                (
                    f"OFFICIAL EVIDENCE URL:\n"
                    f"{page['url']}\n\n"
                    f"PAGE CONTENT:\n"
                    f"{page['content']}"
                )
            )

        return {
            "found": True,
            "source": "official_website",
            "pages": [
                page["url"]
                for page in evidence_pages
            ],
            "evidence": "\n\n---\n\n".join(
                evidence_parts
            ),
            "message": (
                "Explicit affiliate/referral/"
                "commission-related content was "
                "found on the official website."
            ),
        }