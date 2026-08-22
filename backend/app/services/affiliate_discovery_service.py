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
"""

from __future__ import annotations

import re
import html
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests


class AffiliateDiscoveryService:

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
        "earn commission",
        "recurring commission",
        "commission",
        "cookie window",
        "cookie duration",
        "affiliate dashboard",
        "partner program",
        "impact",
        "partnerstack",
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


    def discover(
        self,
        website_url: str,
    ) -> dict:


        website_url = self._normalize_url(
            website_url
        )


        urls = self._build_candidate_urls(
            website_url
        )


        evidence = []


        for url in urls:

            content = self._fetch(
                url
            )

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



    # --------------------------------------------------
    # URL
    # --------------------------------------------------

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

            url = (
                "https://"
                + url
            )


        parsed = urlparse(
            url
        )


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



    # --------------------------------------------------
    # Fetch
    # --------------------------------------------------

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



    # --------------------------------------------------
    # Detection
    # --------------------------------------------------

    def _contains_affiliate_signal(
        self,
        content: str,
    ) -> bool:


        text = self._clean_text(
            content
        )


        return any(
            keyword in text
            for keyword in self.AFFILIATE_KEYWORDS
        )



    # --------------------------------------------------
    # Extraction
    # --------------------------------------------------

    def _extract_information(
        self,
        url: str,
        content: str,
    ) -> dict:


        text = self._clean_text(
            content
        )


        return {

            "url": url,

            "commission": self._extract_commission(
                text
            ),

            "cookie_window": self._extract_cookie_window(
                text
            ),

            "platform": self._extract_platform(
                text
            ),

            "evidence": self._build_evidence(
                text
            ),

        }



    def _extract_commission(
        self,
        text: str,
    ) -> dict:


        patterns = [

            r"(\d+(?:\.\d+)?)%"
            r"\s+(?:monthly\s+)?"
            r"(?:recurring\s+)?"
            r"commission",

            r"(\d+(?:\.\d+)?)%"
            r"\s+recurring",

            r"earn\s+"
            r"(\d+(?:\.\d+)?)%",

            r"commission\s+"
            r"(?:of|rate)\s+"
            r"(\d+(?:\.\d+)?)%",

            r"(\d+(?:\.\d+)?)"
            r"\s+percent\s+commission",

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



    def _extract_platform(
        self,
        text: str,
    ) -> Optional[str]:


        platforms = [

            "impact",

            "partnerstack",

            "shareasale",

            "awin",

            "cj affiliate",

            "commission junction",

            "rakuten",

        ]


        for platform in platforms:

            if platform in text:

                return platform


        return None



    # --------------------------------------------------
    # Evidence
    # --------------------------------------------------

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

            if any(
                keyword in sentence
                for keyword in self.AFFILIATE_KEYWORDS
            ):

                sentence = sentence.strip()


                if (
                    sentence
                    and sentence not in results
                ):

                    results.append(
                        sentence[:500]
                    )


        return results[:20]



    # --------------------------------------------------
    # Result
    # --------------------------------------------------

    def _build_result(
        self,
        evidence: list[dict],
    ) -> dict:


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



        return {

            "affiliate_program_found": True,

            "affiliate_program_likely": "Yes",

            "commission_type": commission_type,

            "commission_estimate": commission_estimate,

            "cookie_window": (
                cookie
                or "Unknown"
            ),

            "affiliate_platform": (
                platform
                or "Unknown"
            ),

            "program_url": self._best_url(
                evidence
            ),

            "evidence": [
                item
                for row in evidence
                for item in row.get(
                    "evidence",
                    [],
                )
            ],

            "confidence": 100,

        }



    def _best_url(
        self,
        evidence: list[dict],
    ) -> Optional[str]:


        priority = [
            "affiliate",
            "partner",
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


        return content.lower().strip()