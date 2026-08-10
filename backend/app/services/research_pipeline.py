"""
Research Pipeline

Coordinates the website research workflow used by AI workers.
"""

from __future__ import annotations

from app.services.ai_analyzer import AIAnalyzer
from app.services.content_extractor import ContentExtractor
from app.services.website_fetcher import WebsiteFetcher
from app.schemas.affiliate_analysis import AffiliateAnalysis


class ResearchPipeline:
    """
    End-to-end website research pipeline.

    Converts raw AI analyzer output into the
    structured AffiliateAnalysis model expected
    by downstream workflows.
    """

    def __init__(self):

        self.fetcher = WebsiteFetcher()

        self.extractor = ContentExtractor()

        self.analyzer = AIAnalyzer()


    def analyze(
        self,
        url: str,
    ) -> AffiliateAnalysis:

        """
        Analyze a company website and return
        structured affiliate intelligence.
        """

        html = self.fetcher.fetch(
            url
        )


        if not html:

            raise ValueError(
                "Unable to fetch website."
            )


        text = self.extractor.extract(
            html
        )


        if not text:

            raise ValueError(
                "No readable content extracted."
            )


        raw_result = self.analyzer.analyze_product(
            website_url=url,
            website_text=text,
        )


        # --------------------------------------------------
        # Normalize AI output
        # --------------------------------------------------

        if isinstance(
            raw_result,
            AffiliateAnalysis,
        ):

            return raw_result


        if isinstance(
            raw_result,
            dict,
        ):

            return AffiliateAnalysis.model_validate(
                raw_result
            )


        raise TypeError(
            "AIAnalyzer returned an unsupported "
            f"result type: {type(raw_result).__name__}"
        )