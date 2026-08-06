"""
Research Pipeline

Coordinates the website research workflow used by AI workers.
"""

from __future__ import annotations

from app.services.ai_analyzer import AIAnalyzer
from app.services.content_extractor import ContentExtractor
from app.services.website_fetcher import WebsiteFetcher


class ResearchPipeline:
    """
    End-to-end website research pipeline.
    """

    def __init__(self):
        self.fetcher = WebsiteFetcher()
        self.extractor = ContentExtractor()
        self.analyzer = AIAnalyzer()

    def analyze(
        self,
        url: str,
    ) -> dict:
        """
        Analyze a company website.
        """

        html = self.fetcher.fetch(url)

        if not html:
            return {
                "success": False,
                "error": "Unable to fetch website.",
            }

        text = self.extractor.extract(html)

        if not text:

            return {
                "success": False,
                "error": "No readable content extracted.",
            }

        return self.analyzer.analyze_product(
            website_url=url,
            website_text=text,
        )