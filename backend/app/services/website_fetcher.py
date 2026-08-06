"""
Website Fetcher Service

Downloads website content for AI workers.
"""

from __future__ import annotations

from typing import Optional

import httpx


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

            return response.text

        except Exception:

            return None