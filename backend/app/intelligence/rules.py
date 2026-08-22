"""
Affiliate Intelligence Rules

Deterministic business rules for evaluating
affiliate opportunities.

Important design principle:

Unknown affiliate information is NOT treated as
proof that an affiliate program does not exist.

The system separates:

1. Commercial attractiveness
2. Affiliate-program verification
3. Commission transparency
"""

from __future__ import annotations

from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.intelligence.models import IntelligenceReason
from app.intelligence.weights import DEFAULT_WEIGHTS


class AffiliateRules:
    """
    Evaluates an AffiliateAnalysis and produces
    explainable deterministic scoring reasons.
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
        ).strip().lower()

        summary = (
            analysis.summary or ""
        ).lower()

        commission = (
            analysis.commission_estimate or ""
        ).strip().lower()

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

        if any(
            phrase in pricing
            for phrase in (
                "subscription",
                "recurring",
                "monthly",
                "annual",
                "yearly",
                "saas",
                "tiered",
            )
        ):

            reasons.append(
                IntelligenceReason(
                    title="Subscription Revenue",
                    points=(
                        DEFAULT_WEIGHTS
                        .subscription_pricing
                    ),
                    description=(
                        "Subscription-based products can "
                        "create recurring customer value."
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
            or "usage-based" in pricing
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
            or "ai" in summary
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
            or "enterprise" in category
        ):

            reasons.append(
                IntelligenceReason(
                    title="Enterprise Market",
                    points=(
                        DEFAULT_WEIGHTS
                        .enterprise_market
                    ),
                    description=(
                        "Enterprise customers can have "
                        "higher lifetime value."
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
                "businesses",
                "teams",
                "team",
                "company",
                "companies",
                "enterprise",
                "small business",
                "mid-sized",
                "mid-sized businesses",
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
                "professional",
                "pro",
                "business",
                "high ticket",
                "high-ticket",
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
            or "free tools" in summary
            or "free plan" in pricing
            or "freemium" in pricing
        ):

            reasons.append(
                IntelligenceReason(
                    title="Low-Friction Entry",
                    points=(
                        DEFAULT_WEIGHTS
                        .free_trial
                    ),
                    description=(
                        "Free entry points can reduce "
                        "conversion friction."
                    ),
                )
            )

        # ==================================================
        # AFFILIATE VERIFICATION
        # ==================================================

        # IMPORTANT:
        #
        # Unknown does NOT receive a -20 penalty.
        #
        # Unknown means:
        #
        # "We don't have enough evidence yet."
        #
        # That should trigger a verification workflow,
        # not destroy the commercial score.

        if affiliate in {
            "no",
            "none",
            "not available",
            "no affiliate",
            "no affiliate program",
        }:

            reasons.append(
                IntelligenceReason(
                    title="No Affiliate Program Confirmed",
                    points=-25,
                    description=(
                        "The supplied evidence indicates "
                        "that no usable affiliate program exists."
                    ),
                )
            )

        elif affiliate in {
            "unknown",
            "",
            "uncertain",
            "unclear",
            "possible",
            "likely",
        }:

            reasons.append(
                IntelligenceReason(
                    title="Affiliate Program Requires Verification",
                    points=0,
                    description=(
                        "The supplied website content does not "
                        "provide enough evidence to confirm an "
                        "affiliate program. Further research is required."
                    ),
                )
            )

        # ==================================================
        # COMMISSION TRANSPARENCY
        # ==================================================

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
                    title="Commission Requires Verification",
                    points=0,
                    description=(
                        "Affiliate payout information is not "
                        "confirmed by the supplied website evidence."
                    ),
                )
            )

        # ==================================================
        # RETURN
        # ==================================================

        return reasons