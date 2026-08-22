"""
Website Research Service

Discovers and fetches relevant internal pages from a company
website before AI analysis.

The service:
1. Fetches the homepage.
2. Discovers relevant internal links.
3. Probes common affiliate/referral/partner paths.
4. Fetches valid pages.
5. Builds a combined research corpus.
"""

from __future__ import annotations

from typing import List
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.website_fetcher import WebsiteFetcher
from app.services.content_extractor import ContentExtractor


class WebsiteResearchService:
    """
    Discover relevant pages on a company website and build
    a combined research corpus.
    """

    MAX_PAGES = 10

    RELEVANT_KEYWORDS = (
        "affiliate",
        "affiliates",
        "affiliate-program",
        "referral",
        "referrals",
        "partner",
        "partners",
        "partnership",
        "partnerships",
        "commission",
        "creator",
        "creators",
        "ambassador",
    )

    CANDIDATE_PATHS = (
        "/affiliate",
        "/affiliates",
        "/affiliate-program",
        "/affiliate-programs",
        "/referral",
        "/referrals",
        "/referral-program",
        "/referral-programs",
        "/partners",
        "/partner",
        "/partnership",
        "/partnerships",
        "/affiliate-partners",
        "/partner-program",
        "/partner-programs",
        "/creator",
        "/creators",
        "/ambassador",
        "/ambassadors",
    )

    def __init__(
        self,
        timeout: float = 10.0,
    ):
        self.fetcher = WebsiteFetcher(
            timeout=timeout
        )

        self.extractor = ContentExtractor()

        self.timeout = timeout

    # ==========================================================
    # DOMAIN CHECK
    # ==========================================================

    def _same_domain(
        self,
        base_url: str,
        target_url: str,
    ) -> bool:

        base_domain = (
            urlparse(
                base_url
            )
            .netloc
            .lower()
            .replace(
                "www.",
                "",
            )
        )

        target_domain = (
            urlparse(
                target_url
            )
            .netloc
            .lower()
            .replace(
                "www.",
                "",
            )
        )

        return (
            base_domain
            == target_domain
        )

    # ==========================================================
    # RELEVANT LINK CHECK
    # ==========================================================

    def _is_relevant_link(
        self,
        url: str,
    ) -> bool:

        value = url.lower()

        return any(
            keyword in value
            for keyword in self.RELEVANT_KEYWORDS
        )

    # ==========================================================
    # LINK DISCOVERY
    # ==========================================================

    def _discover_links(
        self,
        base_url: str,
        html: str,
    ) -> List[str]:

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        discovered = []

        for tag in soup.find_all(
            "a",
            href=True,
        ):

            href = tag.get(
                "href"
            )

            if not href:
                continue

            absolute_url = urljoin(
                base_url,
                href,
            )

            parsed = urlparse(
                absolute_url
            )

            if parsed.scheme not in (
                "http",
                "https",
            ):
                continue

            if not self._same_domain(
                base_url,
                absolute_url,
            ):
                continue

            if not self._is_relevant_link(
                absolute_url
            ):
                continue

            clean_url = (
                f"{parsed.scheme}://"
                f"{parsed.netloc}"
                f"{parsed.path}"
            )

            if (
                clean_url not in discovered
            ):
                discovered.append(
                    clean_url
                )

        return discovered

    # ==========================================================
    # CANDIDATE URL GENERATION
    # ==========================================================

    def _candidate_urls(
        self,
        base_url: str,
    ) -> List[str]:

        parsed = urlparse(
            base_url
        )

        root = (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
        )

        return [
            urljoin(
                root + "/",
                path.lstrip("/"),
            )
            for path in self.CANDIDATE_PATHS
        ]

    # ==========================================================
    # CHECK WHETHER URL EXISTS
    # ==========================================================

    def _url_exists(
        self,
        url: str,
    ) -> bool:

        headers = {
            "User-Agent": (
                "ETM Affiliate OS/0.4 "
                "(https://github.com/"
                "blackaccountant/"
                "etm-affiliate-os)"
            )
        }

        try:

            response = httpx.get(
                url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )

            if (
                response.status_code
                >= 400
            ):
                return False

            content_type = (
                response.headers
                .get(
                    "content-type",
                    "",
                )
                .lower()
            )

            return (
                "text/html"
                in content_type
            )

        except Exception:

            return False

    # ==========================================================
    # FETCH PAGE
    # ==========================================================

    def _fetch_page(
        self,
        url: str,
    ):

        return self.fetcher.fetch(
            url
        )

    # ==========================================================
    # MAIN RESEARCH
    # ==========================================================

    def research(
        self,
        url: str,
    ) -> str:

        """
        Fetch the homepage, discover relevant internal
        pages, probe likely affiliate/referral/partner
        URLs, and combine all readable content.
        """

        homepage_html = (
            self._fetch_page(
                url
            )
        )

        if not homepage_html:

            raise ValueError(
                "Unable to fetch website."
            )

        pages = [
            url
        ]

        # ------------------------------------------------------
        # 1. Discover relevant links from homepage
        # ------------------------------------------------------

        discovered_links = (
            self._discover_links(
                url,
                homepage_html,
            )
        )

        for link in discovered_links:

            if link not in pages:

                pages.append(
                    link
                )

            if (
                len(pages)
                >= self.MAX_PAGES
            ):
                break

        # ------------------------------------------------------
        # 2. Probe common affiliate/referral/partner paths
        # ------------------------------------------------------

        if (
            len(pages)
            < self.MAX_PAGES
        ):

            candidate_urls = (
                self._candidate_urls(
                    url
                )
            )

            for candidate in candidate_urls:

                if candidate in pages:
                    continue

                if not self._same_domain(
                    url,
                    candidate,
                ):
                    continue

                if not self._url_exists(
                    candidate
                ):
                    continue

                pages.append(
                    candidate
                )

                if (
                    len(pages)
                    >= self.MAX_PAGES
                ):
                    break

        # ------------------------------------------------------
        # 3. Fetch and extract all selected pages
        # ------------------------------------------------------

        research_sections = []

        for page_url in pages:

            if page_url == url:

                html = (
                    homepage_html
                )

            else:

                html = (
                    self._fetch_page(
                        page_url
                    )
                )

            if not html:
                continue

            text = (
                self.extractor.extract(
                    html
                )
            )

            if not text:
                continue

            research_sections.append(
                (
                    "SOURCE URL:\n"
                    f"{page_url}\n\n"
                    "CONTENT:\n"
                    f"{text}"
                )
            )

        # ------------------------------------------------------
        # 4. Validate research result
        # ------------------------------------------------------

        if not research_sections:

            raise ValueError(
                "No readable website "
                "content found."
            )

        return "\n\n".join(
            research_sections
        )