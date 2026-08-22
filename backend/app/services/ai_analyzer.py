"""
AI Analyzer Service

Uses the AI Manager to analyze website content and return
structured affiliate research.

The AI extracts business facts.

The deterministic AffiliateScoringEngine is responsible
for calculating the final affiliate score.
"""

from __future__ import annotations

import json

from app.ai.manager import AIManager
from app.schemas.affiliate_analysis import AffiliateAnalysis


class AIAnalyzer:
    """
    Analyze website content using AI.

    The AI does NOT calculate the final affiliate score.

    It extracts structured business facts which are later
    evaluated by the deterministic scoring engine.
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

        # --------------------------------------------------
        # Limit website content sent to the AI provider.
        # --------------------------------------------------

        website_text = (website_text or "")[:12000]

        prompt = f"""
You are a factual business research extraction system.

Your ONLY job is to extract facts that are supported by
the supplied website content.

Do NOT guess.

Do NOT infer facts merely because they are common for
companies in the same industry.

Do NOT calculate an affiliate score.

Do NOT make commercial assumptions.

Website URL:
{website_url}

Website Content:
{website_text}

Return ONLY valid JSON.

Use exactly this schema:

{{
    "company": "",
    "website": "{website_url}",
    "category": "",
    "summary": "",
    "target_audience": [],
    "pricing_model": "",
    "affiliate_program_likely": "Unknown",
    "commission_type": "Unknown",
    "commission_estimate": "Unknown",
    "affiliate_score": 0,
    "recommendation": ""
}}

==================================================
AFFILIATE PROGRAM EVIDENCE RULES
==================================================

"affiliate_program_likely" MUST be exactly one of:

"Yes"
"No"
"Unknown"

Use "Yes" ONLY if the supplied website content contains
explicit evidence of an affiliate program.

Examples of acceptable evidence:

- affiliate program
- affiliate
- affiliate commission
- affiliate partner
- referral program
- referral partner
- partner program that explicitly provides referral
  commissions
- an explicit statement describing how affiliates earn
  commissions

Do NOT infer "Yes" from:

- SaaS pricing
- recurring subscriptions
- high customer lifetime value
- partner ecosystems
- integrations
- reseller programs
- agencies
- marketplaces
- customer referral features
- general partnerships
- the company's popularity
- the existence of an affiliate program elsewhere on
  the internet

If the website content does not explicitly establish
an affiliate program, return:

"Unknown"

Use "No" ONLY if the supplied website content explicitly
states that the company does not have an affiliate program.

==================================================
COMMISSION RULES
==================================================

If affiliate_program_likely is "Unknown":

commission_type MUST be:

"Unknown"

commission_estimate MUST be:

"Unknown"

If affiliate_program_likely is "No":

commission_type MUST be:

"Unknown"

commission_estimate MUST be:

"Unknown"

Only populate commission_type when the supplied content
explicitly describes the commission structure.

Only populate commission_estimate when the supplied
content explicitly provides a commission amount,
percentage, duration, or clearly stated payout structure.

Never invent a percentage.

Never estimate a commission.

Never use outside knowledge.

==================================================
SCORING RULE
==================================================

"affiliate_score" MUST ALWAYS be:

0

The deterministic scoring engine calculates the actual
affiliate opportunity score later.

==================================================
RECOMMENDATION RULE
==================================================

The recommendation must be factual.

Do not assign a numerical score.

Do not invent an affiliate program.

If affiliate evidence is unknown, clearly state that
affiliate-program verification requires further research.

==================================================
GENERAL EXTRACTION RULES
==================================================

1. Do not invent information.

2. Use only information supported by the supplied
   website content.

3. "target_audience" must be a JSON array of strings.

4. Do not add speculative audiences.

5. "summary" must be concise and factual.

6. "pricing_model" must describe only supported pricing
   information.

7. Use "Unknown" whenever information is unavailable.

8. Do not use:

   "Not confirmed"
   "N/A"
   "Unavailable"
   "Could not determine"

   Use:

   "Unknown"

9. Keep factual fields concise.

10. Avoid unnecessary stylistic variation.

11. Return JSON only.

12. Do not include markdown.

13. Do not include explanations outside the JSON.
"""

        result = self.ai.generate(
            prompt=prompt,
        )

        if not result.success:
            raise RuntimeError(
                result.error or "AI request failed."
            )

        try:
            data = json.loads(
                result.content
            )

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid AI JSON response: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "AI response must be a JSON object."
            )

        # --------------------------------------------------
        # Normalize affiliate program status.
        # --------------------------------------------------

        affiliate_program = str(
            data.get(
                "affiliate_program_likely",
                "Unknown",
            )
        ).strip().lower()

        if affiliate_program == "yes":
            affiliate_program = "Yes"

        elif affiliate_program == "no":
            affiliate_program = "No"

        else:
            affiliate_program = "Unknown"

        data["affiliate_program_likely"] = (
            affiliate_program
        )

        # --------------------------------------------------
        # Normalize commission fields.
        #
        # Commission information is only meaningful when
        # an affiliate/referral program is actually
        # supported by evidence.
        # --------------------------------------------------

        if affiliate_program in {
            "Unknown",
            "No",
        }:
            data["commission_type"] = "Unknown"
            data["commission_estimate"] = "Unknown"

        else:

            commission_type = data.get(
                "commission_type"
            )

            if not commission_type:
                commission_type = "Unknown"

            data["commission_type"] = str(
                commission_type
            ).strip()

            commission_estimate = data.get(
                "commission_estimate"
            )

            if not commission_estimate:
                commission_estimate = "Unknown"

            data["commission_estimate"] = str(
                commission_estimate
            ).strip()

        # --------------------------------------------------
        # Normalize target audience.
        # --------------------------------------------------

        target_audience = data.get(
            "target_audience"
        )

        if not isinstance(
            target_audience,
            list,
        ):
            target_audience = []

        normalized_audience = []

        for item in target_audience:

            if item is None:
                continue

            value = str(item).strip()

            if not value:
                continue

            if value not in normalized_audience:
                normalized_audience.append(value)

        data["target_audience"] = (
            normalized_audience
        )

        # --------------------------------------------------
        # Normalize basic text fields.
        # --------------------------------------------------

        for field in [
            "company",
            "category",
            "summary",
            "pricing_model",
            "recommendation",
        ]:

            value = data.get(field)

            if value is None:
                data[field] = ""

            else:
                data[field] = str(value).strip()

        # --------------------------------------------------
        # Deterministic scoring engine owns the score.
        # --------------------------------------------------

        data["affiliate_score"] = 0

        # --------------------------------------------------
        # Validate against AffiliateAnalysis.
        # --------------------------------------------------

        try:

            return AffiliateAnalysis.model_validate(
                data
            )

        except Exception as exc:

            raise RuntimeError(
                f"Invalid AffiliateAnalysis data: {exc}"
            ) from exc