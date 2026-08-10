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
    explainable scoring reasons.
    """

    def evaluate(
        self,
        analysis: AffiliateAnalysis,
    ) -> list[IntelligenceReason]:

        reasons: list[IntelligenceReason] = []

        pricing = (
            analysis.pricing_model or ""
        ).lower()

        audience = " ".join(
            analysis.target_audience or []
        ).lower()

        category = (
            analysis.category or ""
        ).lower()

        affiliate = (
            analysis.affiliate_program_likely or ""
        ).lower()

        summary = (
            analysis.summary or ""
        ).lower()

        commission = (
            analysis.commission_estimate or ""
        ).lower()

        # ==================================================
        # POSITIVE SIGNALS
        # ==================================================

        # ------------------------------------------
        # Official Affiliate Program
        # ------------------------------------------

        if affiliate in {
            "yes",
            "available",
            "official",
            "confirmed",
        }:

            reasons.append(
                IntelligenceReason(
                    title="Official Affiliate Program",
                    points=(
                        DEFAULT_WEIGHTS
                        .official_affiliate_program
                    ),
                    description=(
                        "A confirmed affiliate program "
                        "reduces monetization uncertainty."
                    ),
                )
            )

        # ------------------------------------------
        # Subscription Revenue
        # ------------------------------------------

        if "subscription" in pricing:

            reasons.append(
                IntelligenceReason(
                    title="Subscription Revenue",
                    points=(
                        DEFAULT_WEIGHTS
                        .subscription_pricing
                    ),
                    description=(
                        "Subscription products can "
                        "create recurring affiliate value."
                    ),
                )
            )

        # ------------------------------------------
        # Usage-Based Revenue
        # ------------------------------------------

        if (
            "usage" in pricing
            or "pay as you go" in pricing
            or "pay-as-you-go" in pricing
            or "credits" in pricing
        ):

            reasons.append(
                IntelligenceReason(
                    title="Usage-Based Revenue",
                    points=(
                        DEFAULT_WEIGHTS
                        .usage_based_pricing
                    ),
                    description=(
                        "Usage-based products can "
                        "generate ongoing customer value."
                    ),
                )
            )

        # ------------------------------------------
        # AI Category
        # ------------------------------------------

        if (
            "ai" in category
            or "artificial intelligence" in category
            or "machine learning" in category
        ):

            reasons.append(
                IntelligenceReason(
                    title="AI Market",
                    points=(
                        DEFAULT_WEIGHTS
                        .ai_category
                    ),
                    description=(
                        "AI products operate in a "
                        "high-growth technology market."
                    ),
                )
            )

        # ------------------------------------------
        # Developer Market
        # ------------------------------------------

        if (
            "developer" in audience
            or "software engineer" in audience
            or "software engineering" in audience
            or "engineer" in audience
        ):

            reasons.append(
                IntelligenceReason(
                    title="Developer Market",
                    points=(
                        DEFAULT_WEIGHTS
                        .developer_market
                    ),
                    description=(
                        "Developer-focused products "
                        "can have strong SaaS adoption."
                    ),
                )
            )

        # ------------------------------------------
        # Enterprise Market
        # ------------------------------------------

        if (
            "enterprise" in audience
            or "enterprise" in pricing
            or "enterprise" in summary
        ):

            reasons.append(
                IntelligenceReason(
                    title="Enterprise Market",
                    points=(
                        DEFAULT_WEIGHTS
                        .enterprise_market
                    ),
                    description=(
                        "Enterprise customers can "
                        "have higher lifetime value."
                    ),
                )
            )

        # ------------------------------------------
        # Global / Broad Market
        # ------------------------------------------

        if any(
            word in audience
            for word in (
                "global",
                "startup",
                "business",
                "teams",
                "team",
            )
        ):

            reasons.append(
                IntelligenceReason(
                    title="Broad Market",
                    points=(
                        DEFAULT_WEIGHTS
                        .global_market
                    ),
                    description=(
                        "A broad target market increases "
                        "the potential affiliate audience."
                    ),
                )
            )

        # ------------------------------------------
        # High-Ticket Potential
        # ------------------------------------------

        if any(
            word in pricing
            for word in (
                "enterprise",
                "premium",
                "pro",
                "high ticket",
            )
        ):

            reasons.append(
                IntelligenceReason(
                    title="High-Ticket Potential",
                    points=(
                        DEFAULT_WEIGHTS
                        .high_ticket
                    ),
                    description=(
                        "Higher-value products can "
                        "produce larger commissions."
                    ),
                )
            )

        # ------------------------------------------
        # Free Trial
        # ------------------------------------------

        if (
            "free trial" in summary
            or "free trial" in pricing
        ):

            reasons.append(
                IntelligenceReason(
                    title="Free Trial",
                    points=(
                        DEFAULT_WEIGHTS
                        .free_trial
                    ),
                    description=(
                        "Free trials can reduce "
                        "conversion friction."
                    ),
                )
            )

        # ==================================================
        # NEGATIVE SIGNALS
        # ==================================================

        # ------------------------------------------
        # Affiliate Program Uncertainty
        # ------------------------------------------

        uncertain_affiliate = any(
            phrase in affiliate
            for phrase in (
                "unknown",
                "possible",
                "uncertain",
                "unclear",
                "not clearly",
                "not visible",
                "not confirmed",
                "likely",
            )
        )

        confirmed_negative_affiliate = any(
            phrase in affiliate
            for phrase in (
                "no affiliate",
                "not available",
                "none",
                "does not have",
                "no public affiliate",
            )
        )

        if confirmed_negative_affiliate:

            reasons.append(
                IntelligenceReason(
                    title="No Affiliate Program Confirmed",
                    points=-25,
                    description=(
                        "No usable affiliate program "
                        "was identified."
                    ),
                )
            )

        elif uncertain_affiliate:

            reasons.append(
                IntelligenceReason(
                    title="Affiliate Program Uncertain",
                    points=-20,
                    description=(
                        "The company may have an affiliate "
                        "or referral opportunity, but it "
                        "has not been clearly confirmed."
                    ),
                )
            )

        # ------------------------------------------
        # Commission Unknown
        # ------------------------------------------

        commission_unknown = (
            not commission
            or commission in {
                "unknown",
                "not publicly stated",
                "not available",
                "n/a",
                "none",
            }
        )

        if commission_unknown:

            reasons.append(
                IntelligenceReason(
                    title="Commission Unknown",
                    points=-10,
                    description=(
                        "Affiliate payout information "
                        "is unavailable or unconfirmed."
                    ),
                )
            )

        return reasons