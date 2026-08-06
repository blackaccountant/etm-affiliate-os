"""
Content Extractor Service

Extracts readable text from HTML pages.
"""

from __future__ import annotations

from bs4 import BeautifulSoup


class ContentExtractor:
    """
    Convert HTML into clean readable text.
    """

    def extract(
        self,
        html: str,
    ) -> str:
        """
        Extract readable text from HTML.
        """

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        # Remove unwanted elements
        for tag in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "img",
                "iframe",
                "footer",
                "header",
            ]
        ):
            tag.decompose()

        text = soup.get_text(
            separator=" ",
            strip=True,
        )

        # Normalize whitespace
        text = " ".join(text.split())

        return text