"""
AI Analyzer Service

Uses the AI Manager to analyze website content and
return structured affiliate intelligence.
"""

from __future__ import annotations

import json

from app.ai.manager import AIManager
from app.schemas.affiliate_analysis import AffiliateAnalysis


class AIAnalyzer:
    """
    Analyze website content using AI.
    """

    def __init__(self):
        self.ai = AIManager()

    def analyze_product(
        self,
        website_url: str,
        website_text: str,
    ) -> AffiliateAnalysis:
        """
        Analyze a company's website and return a validated
        AffiliateAnalysis object.
        """

        # Prevent sending extremely large pages
        website_text = website_text[:12000]

        prompt = f"""
You are an affiliate marketing research analyst.

Analyze the following company website.

Website:
{website_url}

Website Content:
{website_text}

Return ONLY valid JSON.

Use this schema:

{{
    "company": "",
    "website": "{website_url}",
    "category": "",
    "summary": "",
    "target_audience": [],
    "pricing_model": "",
    "affiliate_program_likely": "",
    "commission_type": "",
    "commission_estimate": "",
    "affiliate_score": 0,
    "recommendation": ""
}}

Do not include markdown.

Do not explain anything.

Return JSON only.
"""

        result = self.ai.generate(
            prompt=prompt,
        )

        if not result.success:
            raise RuntimeError(
                result.error or "AI request failed."
            )

        try:

            data = json.loads(result.content)

            return AffiliateAnalysis.model_validate(data)

        except Exception as exc:

            raise RuntimeError(
                f"Invalid AI response: {exc}"
            ) from exc