"""
Research Pipeline

Coordinates the website research workflow used by AI workers.
"""

from __future__ import annotations

from app.services.ai_analyzer import AIAnalyzer
from app.services.website_research_service import (
    WebsiteResearchService,
)
from app.schemas.affiliate_analysis import AffiliateAnalysis


class ResearchPipeline:
    """
    End-to-end website research pipeline.

    Flow:

        Website
            ↓
        Page Discovery
            ↓
        Multi-page Research
            ↓
        AI Analysis
            ↓
        AffiliateAnalysis
    """

    def __init__(self):

        self.researcher = (
            WebsiteResearchService()
        )

        self.analyzer = (
            AIAnalyzer()
        )

    def analyze(
        self,
        url: str,
    ) -> AffiliateAnalysis:

        """
        Research a website and return
        structured affiliate intelligence.
        """

        if not url:

            raise ValueError(
                "A URL is required."
            )

        # --------------------------------------------------
        # Step 1 - Multi-page website research
        # --------------------------------------------------

        research_text = (
            self.researcher.research(
                url
            )
        )

        if not research_text:

            raise ValueError(
                "No readable website content found."
            )

        # --------------------------------------------------
        # Step 2 - AI factual analysis
        # --------------------------------------------------

        raw_result = (
            self.analyzer.analyze_product(
                website_url=url,
                website_text=research_text,
            )
        )

        # --------------------------------------------------
        # Step 3 - Normalize result
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
            f"result type: "
            f"{type(raw_result).__name__}"
        )