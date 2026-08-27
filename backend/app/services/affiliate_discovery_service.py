"""
Affiliate Discovery Service

Discovers affiliate programs from websites.

Extracts:

- affiliate program existence
- affiliate network/platform
- commission structure
- commission value
- cookie duration
- affiliate program URL
- evidence
- confidence
"""

from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests


class AffiliateDiscoveryService:
    """
    Deterministic affiliate-program discovery service.

    The service distinguishes between:

    - Yes:
        Strong evidence supports an affiliate program.

    - Likely:
        Affiliate-related evidence exists, but verification
        is incomplete.

    - Unknown:
        No meaningful affiliate evidence was found.
    """

    TIMEOUT = 15

    COMMON_PATHS = [
        "/partners/affiliates",
        "/partners/affiliate",
        "/affiliate",
        "/affiliates",
        "/affiliate-program",
        "/affiliate-programs",
        "/partners",
        "/partner-program",
        "/referral",
        "/referrals",
    ]

    AFFILIATE_KEYWORDS = [
        "affiliate program",
        "affiliate partner",
        "affiliate marketing",
        "become an affiliate",
        "join our affiliate",
        "join the affiliate",
        "join our affiliate program",
        "apply to our affiliate program",
        "affiliate application",
        "affiliate dashboard",
        "affiliate commission",
        "affiliate commissions",
        "affiliate payout",
        "affiliate payouts",
        "recurring commission",
        "affiliate terms",
        "affiliate terms and conditions",
    ]

    WEAK_AFFILIATE_KEYWORDS = [
        "affiliate",
        "commission",
        "referral",
        "partner program",
    ]

    PLATFORM_NAMES = [
        "impact",
        "partnerstack",
        "shareasale",
        "awin",
        "cj affiliate",
        "commission junction",
        "rakuten",
    ]

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "Chrome/142 Safari/537"
                )
            }
        )

    # ==================================================
    # PUBLIC DISCOVERY
    # ==================================================

    def discover(
        self,
        website_url: str,
    ) -> dict:
        """
        Discover affiliate-program evidence from a website.
        """

        website_url = self._normalize_url(
            website_url
        )

        urls = self._build_candidate_urls(
            website_url
        )

        evidence = []

        for url in urls:
            content = self._fetch(url)

            if not content:
                continue

            if not self._contains_affiliate_signal(
                content
            ):
                continue

            evidence.append(
                self._extract_information(
                    url,
                    content,
                )
            )

        return self._build_result(
            evidence
        )

    # ==================================================
    # URL
    # ==================================================

    def _normalize_url(
        self,
        url: str,
    ) -> str:
        url = url.strip()

        if not url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            url = "https://" + url

        parsed = urlparse(url)

        return (
            f"{parsed.scheme}://{parsed.netloc}"
        ).rstrip("/")

    def _build_candidate_urls(
        self,
        website_url: str,
    ) -> list[str]:
        urls = [
            website_url
        ]

        for path in self.COMMON_PATHS:
            urls.append(
                urljoin(
                    website_url + "/",
                    path.lstrip("/"),
                )
            )

        return urls

    # ==================================================
    # FETCH
    # ==================================================

    def _fetch(
        self,
        url: str,
    ) -> Optional[str]:
        try:
            response = self.session.get(
                url,
                timeout=self.TIMEOUT,
                allow_redirects=True,
            )

            if response.status_code != 200:
                return None

            return response.text

        except requests.RequestException:
            return None

    # ==================================================
    # DETECTION
    # ==================================================

    def _contains_affiliate_signal(
        self,
        content: str,
    ) -> bool:
        text = self._clean_text(
            content
        )

        strong_signal = any(
            keyword in text
            for keyword in self.AFFILIATE_KEYWORDS
        )

        if strong_signal:
            return True

        # A generic "affiliate" mention is not enough
        # unless it appears with another meaningful
        # affiliate-related term.
        has_affiliate = (
            "affiliate" in text
        )

        has_supporting_signal = any(
            keyword in text
            for keyword in (
                "commission",
                "dashboard",
                "application",
                "apply",
                "join",
                "payout",
                "terms",
            )
        )

        return (
            has_affiliate
            and has_supporting_signal
        )

    # ==================================================
    # EXTRACTION
    # ==================================================

    def _extract_information(
        self,
        url: str,
        content: str,
    ) -> dict:
        text = self._clean_text(
            content
        )

        affiliate_evidence = (
            self._build_evidence(
                text
            )
        )

        evidence_text = " ".join(
            affiliate_evidence
        )

        return {
            "url": url,
            "commission": self._extract_commission(
                evidence_text
                if evidence_text
                else text
            ),
            "cookie_window": self._extract_cookie_window(
                evidence_text
                if evidence_text
                else text
            ),
            "platform": self._extract_platform(
                evidence_text
                if evidence_text
                else ""
            ),
            "affiliate_signal": (
                self._has_strong_affiliate_signal(
                    text
                )
            ),
            "evidence": affiliate_evidence,
        }

    # ==================================================
    # COMMISSION
    # ==================================================

    def _extract_commission(
        self,
        text: str,
    ) -> dict:
        patterns = [
            (
                r"(\d+(?:\.\d+)?)%"
                r"\s+(?:monthly\s+)?"
                r"(?:recurring\s+)?"
                r"commission"
            ),
            (
                r"(\d+(?:\.\d+)?)%"
                r"\s+recurring"
            ),
            (
                r"earn\s+"
                r"(\d+(?:\.\d+)?)%"
            ),
            (
                r"commission\s+"
                r"(?:of|rate)\s+"
                r"(\d+(?:\.\d+)?)%"
            ),
            (
                r"(\d+(?:\.\d+)?)"
                r"\s+percent\s+commission"
            ),
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return {
                    "type": "percentage",
                    "rate": float(
                        match.group(1)
                    ),
                    "raw": match.group(0),
                }

        return {
            "type": "unknown",
            "rate": None,
            "raw": None,
        }

    # ==================================================
    # COOKIE
    # ==================================================

    def _extract_cookie_window(
        self,
        text: str,
    ) -> Optional[str]:
        patterns = [
            r"(\d+)[-\s]?day\s+cookie\s+window",
            r"(\d+)[-\s]?day\s+cookie",
            r"cookie.{0,50}?(\d+)\s+days",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return (
                    f"{match.group(1)} days"
                )

        return None

    # ==================================================
    # PLATFORM
    # ==================================================

    def _extract_platform(
        self,
        text: str,
    ) -> Optional[str]:
        for platform in self.PLATFORM_NAMES:
            if platform in text:
                return platform

        return None

    # ==================================================
    # AFFILIATE SIGNAL
    # ==================================================

    def _has_strong_affiliate_signal(
        self,
        text: str,
    ) -> bool:
        return any(
            keyword in text
            for keyword in self.AFFILIATE_KEYWORDS
        )

    # ==================================================
    # EVIDENCE
    # ==================================================

    def _build_evidence(
        self,
        text: str,
    ) -> list[str]:
        results = []

        sentences = re.split(
            r"(?<=[.!?])\s+",
            text,
        )

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            strong_match = any(
                keyword in sentence
                for keyword in self.AFFILIATE_KEYWORDS
            )

            contextual_match = (
                "affiliate" in sentence
                and any(
                    word in sentence
                    for word in (
                        "commission",
                        "join",
                        "apply",
                        "program",
                        "dashboard",
                        "payout",
                        "terms",
                    )
                )
            )

            if (
                strong_match
                or contextual_match
            ):
                if sentence not in results:
                    results.append(
                        sentence[:500]
                    )

        return results[:20]

    # ==================================================
    # RESULT
    # ==================================================

    def _build_result(
        self,
        evidence: list[dict],
    ) -> dict:
        """
        Build a deterministic affiliate discovery result.

        Generic partner pages and generic platform
        mentions are not sufficient to confirm
        an affiliate program.
        """

        if not evidence:
            return {
                "affiliate_program_found": False,
                "affiliate_program_likely": "Unknown",
                "commission_type": "Unknown",
                "commission_estimate": "Unknown",
                "cookie_window": "Unknown",
                "affiliate_platform": "Unknown",
                "program_url": None,
                "evidence": [],
                "confidence": 0,
            }

        commission = self._first(
            evidence,
            "commission",
        )

        cookie = self._first(
            evidence,
            "cookie_window",
        )

        platform = self._first(
            evidence,
            "platform",
        )

        program_url = self._best_url(
            evidence
        )

        has_strong_affiliate_signal = any(
            row.get(
                "affiliate_signal",
                False,
            )
            for row in evidence
        )

        rate = None

        if commission:
            rate = commission.get(
                "rate"
            )

        if rate is not None:
            commission_type = "percentage"

            commission_estimate = (
                f"{rate:g}% recurring"
            )
        else:
            commission_type = "Unknown"
            commission_estimate = "Unknown"

        # --------------------------------------------------
        # URL classification
        # --------------------------------------------------

        affiliate_url = False

        if program_url:
            path = urlparse(
                program_url
            ).path.lower()

            affiliate_url = any(
                term in path
                for term in (
                    "/affiliate",
                    "/affiliates",
                    "/affiliate-program",
                    "/affiliate-programs",
                )
            )

        partner_url = False

        if program_url:
            path = urlparse(
                program_url
            ).path.lower()

            partner_url = any(
                term in path
                for term in (
                    "/partner",
                    "/partners",
                    "/partner-program",
                )
            )

        # --------------------------------------------------
        # Evidence strength
        # --------------------------------------------------

        has_commission = (
            rate is not None
        )

        has_cookie = bool(
            cookie
        )

        has_platform = bool(
            platform
        )

        # --------------------------------------------------
        # VERIFIED
        # --------------------------------------------------

        if (
            has_strong_affiliate_signal
            and has_commission
            and (
                has_platform
                or has_cookie
                or affiliate_url
            )
        ):
            affiliate_program_found = True
            affiliate_program_likely = "Yes"
            confidence = 95

        elif (
            has_strong_affiliate_signal
            and affiliate_url
            and (
                has_commission
                or has_cookie
                or has_platform
            )
        ):
            affiliate_program_found = True
            affiliate_program_likely = "Yes"
            confidence = 90

        elif (
            has_strong_affiliate_signal
            and affiliate_url
        ):
            affiliate_program_found = True
            affiliate_program_likely = "Yes"
            confidence = 85

        # --------------------------------------------------
        # LIKELY
        # --------------------------------------------------

        elif (
            has_strong_affiliate_signal
            or has_commission
            or has_cookie
        ):
            affiliate_program_found = False
            affiliate_program_likely = "Likely"
            confidence = 60

        elif (
            has_platform
            and partner_url
        ):
            affiliate_program_found = False
            affiliate_program_likely = "Likely"
            confidence = 50

        # --------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------

        else:
            affiliate_program_found = False
            affiliate_program_likely = "Unknown"
            confidence = 0

        return {
            "affiliate_program_found": (
                affiliate_program_found
            ),
            "affiliate_program_likely": (
                affiliate_program_likely
            ),
            "commission_type": (
                commission_type
            ),
            "commission_estimate": (
                commission_estimate
            ),
            "cookie_window": (
                cookie
                or "Unknown"
            ),
            "affiliate_platform": (
                platform
                or "Unknown"
            ),
            "program_url": program_url,
            "evidence": [
                item
                for row in evidence
                for item in row.get(
                    "evidence",
                    [],
                )
            ],
            "confidence": confidence,
        }

    # ==================================================
    # BEST URL
    # ==================================================

    def _best_url(
        self,
        evidence: list[dict],
    ) -> Optional[str]:
        priority = [
            "affiliate",
            "referral",
        ]

        for item in evidence:
            url = item.get(
                "url",
                "",
            ).lower()

            if any(
                word in url
                for word in priority
            ):
                return item.get(
                    "url"
                )

        return evidence[0].get(
            "url"
        )

    # ==================================================
    # FIRST VALID VALUE
    # ==================================================

    def _first(
        self,
        evidence: list[dict],
        key: str,
    ):
        for item in evidence:
            value = item.get(
                key
            )

            if not value:
                continue

            if key == "commission":
                if isinstance(
                    value,
                    dict,
                ):
                    if value.get(
                        "rate"
                    ) is None:
                        continue

            return value

        return None

    # ==================================================
    # TEXT CLEANING
    # ==================================================

    def _clean_text(
        self,
        content: str,
    ) -> str:
        content = html.unescape(
            content
        )

        content = re.sub(
            r"<script.*?</script>",
            " ",
            content,
            flags=re.I | re.S,
        )

        content = re.sub(
            r"<style.*?</style>",
            " ",
            content,
            flags=re.I | re.S,
        )

        content = re.sub(
            r"<[^>]+>",
            " ",
            content,
        )

        content = re.sub(
            r"\s+",
            " ",
            content,
        )

        return content.strip().lower()