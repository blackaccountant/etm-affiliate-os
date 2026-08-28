"""
Website Fetcher Service

Downloads website content for AI workers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass(frozen=True)
class FetchedWebsitePage:
    """Successful fetch content with the HTTP provenance needed by research."""

    content: str
    http_status: int


class WebsiteFetcher:
    """
    Fetch website HTML.
    """

    def __init__(
        self,
        timeout: float = 15.0,
    ):
        self.timeout = timeout

    def fetch(
        self,
        url: str,
    ) -> Optional[str]:
        """
        Download the HTML content of a webpage.

        Returns:
            HTML string if successful.
            None if the request fails.
        """

        page = self.fetch_with_metadata(url)
        return page.content if page else None

    def fetch_with_metadata(
        self,
        url: str,
    ) -> Optional[FetchedWebsitePage]:
        """Download content while retaining status for page-level provenance."""
        headers = {
            "User-Agent": (
                "ETM Affiliate OS/0.4 "
                "(https://github.com/blackaccountant/etm-affiliate-os)"
            )
        }

        try:

            response = httpx.get(
                url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )

            response.raise_for_status()

            return FetchedWebsitePage(
                content=response.text,
                http_status=response.status_code,
            )

        except Exception:

            return None
