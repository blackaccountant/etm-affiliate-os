"""
Affiliate Intelligence Rules

Business rules for evaluating affiliate opportunities.
"""

from __future__ import annotations

from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.intelligence.models import IntelligenceReason
from app.intelligence.weights import DEFAULT_WEIGHTS


class AffiliateRules:
    """
    Evaluates an AffiliateAnalysis and produces
    scoring reasons.
    """

    def evaluate(
        self,
        analysis: AffiliateAnalysis,
    ) -> list[IntelligenceReason]:

        reasons: list[IntelligenceReason] = []

        pricing = analysis.pricing_model.lower()

        audience = " ".join(
            analysis.target_audience
        ).lower()

        category = analysis.category.lower()

        affiliate = analysis.affiliate_program_likely.lower()

        # ------------------------------------
        # Pricing
        # ------------------------------------

        if "subscription" in pricing:
            reasons.append(
                IntelligenceReason(
                    title="Subscription Pricing",
                    points=DEFAULT_WEIGHTS.subscription_pricing,
                    description="Subscription businesses usually generate recurring revenue."
                )
            )

        if "usage" in pricing:
            reasons.append(
                IntelligenceReason(
                    title="Usage-Based Pricing",
                    points=DEFAULT_WEIGHTS.usage_based_pricing,
                    description="Usage pricing often creates long-term customer value."
                )
            )

        # ------------------------------------
        # AI Industry
        # ------------------------------------

        if "ai" in category:
            reasons.append(
                IntelligenceReason(
                    title="AI Industry",
                    points=DEFAULT_WEIGHTS.ai_category,
                    description="Artificial Intelligence remains a rapidly growing market."
                )
            )

        # ------------------------------------
        # Developer Market
        # ------------------------------------

        if "developer" in audience:
            reasons.append(
                IntelligenceReason(
                    title="Developer Audience",
                    points=DEFAULT_WEIGHTS.developer_market,
                    description="Developers are a valuable recurring SaaS audience."
                )
            )

        # ------------------------------------
        # Global Audience
        # ------------------------------------

        if any(
            word in audience
            for word in [
                "global",
                "enterprise",
                "startup",
            ]
        ):
            reasons.append(
                IntelligenceReason(
                    title="Broad Market",
                    points=DEFAULT_WEIGHTS.global_market,
                    description="Broad market products generally have greater affiliate potential."
                )
            )

        # ------------------------------------
        # Official Affiliate Program
        # ------------------------------------

        if affiliate in [
            "yes",
            "available",
            "official",
            "confirmed",
        ]:
            reasons.append(
                IntelligenceReason(
                    title="Official Affiliate Program",
                    points=DEFAULT_WEIGHTS.official_affiliate_program,
                    description="An official affiliate program significantly increases opportunity."
                )
            )

        return reasons