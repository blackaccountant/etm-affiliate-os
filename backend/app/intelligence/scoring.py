"""
Affiliate Intelligence Scoring Engine

Combines the base affiliate analysis with the results
of the Affiliate Discovery Service.

The scoring engine remains deterministic.

Discovery evidence can strengthen the score when an
affiliate program, commission structure, cookie window,
or affiliate platform has been verified.
"""

from __future__ import annotations

from app.intelligence.models import IntelligenceResult
from app.intelligence.rules import AffiliateRules
from app.intelligence.weights import (
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
)
from app.schemas.affiliate_analysis import AffiliateAnalysis


class AffiliateScoringEngine:
    """
    Scores affiliate opportunities using deterministic
    business rules plus verified affiliate discovery data.
    """

    def __init__(self):

        self.rules = AffiliateRules()

    def score(
        self,
        analysis: AffiliateAnalysis,
        discovery: dict | None = None,
    ) -> IntelligenceResult:
        """
        Score an affiliate opportunity.

        Parameters
        ----------
        analysis:
            Structured product/company analysis.

        discovery:
            Optional result from AffiliateDiscoveryService.

        Discovery can contain fields such as:

            affiliate_program_found
            affiliate_program_likely
            commission_type
            commission_estimate
            cookie_window
            affiliate_platform
            confidence
            evidence
        """

        # ==================================================
        # STEP 1 — BASE ANALYSIS RULES
        # ==================================================

        reasons = list(
            self.rules.evaluate(
                analysis
            )
        )

        # ==================================================
        # STEP 2 — AFFILIATE DISCOVERY SIGNALS
        # ==================================================

        if discovery is not None:

            self._apply_discovery_signals(
                reasons,
                discovery,
            )

        # ==================================================
        # STEP 3 — TOTAL SCORE
        # ==================================================

        total = sum(
            reason.points
            for reason in reasons
        )

        # Keep score within 0-100.
        score = max(
            min(total, 100),
            0,
        )

        # ==================================================
        # STEP 4 — GRADE
        # ==================================================

        if score >= GRADE_A:

            grade = "A"

        elif score >= GRADE_B:

            grade = "B"

        elif score >= GRADE_C:

            grade = "C"

        elif score >= GRADE_D:

            grade = "D"

        else:

            grade = "F"

        # ==================================================
        # STEP 5 — CONFIDENCE
        # ==================================================

        positive_reasons = sum(
            1
            for reason in reasons
            if reason.points > 0
        )

        negative_reasons = sum(
            1
            for reason in reasons
            if reason.points < 0
        )

        confidence = min(
            50
            + (positive_reasons * 10)
            + (negative_reasons * 5),
            100,
        )

        # Verified discovery data should increase
        # confidence because the system has direct
        # evidence rather than inference alone.

        if discovery is not None:

            discovery_confidence = self._safe_int(
                discovery.get(
                    "confidence"
                )
            )

            if discovery_confidence >= 90:

                confidence = min(
                    confidence + 10,
                    100,
                )

        # ==================================================
        # STEP 6 — RECOMMENDATION
        # ==================================================

        recommendation = (
            analysis.recommendation
        )

        # If the discovery engine has actually confirmed
        # an affiliate program, don't allow the old AI
        # analysis text to incorrectly claim that the
        # program is unknown.

        if self._program_verified(
            discovery
        ):

            recommendation = (
                self._build_verified_recommendation(
                    analysis,
                    discovery,
                )
            )

        return IntelligenceResult(
            score=score,
            grade=grade,
            confidence=confidence,
            reasons=reasons,
            summary=analysis.summary,
            recommendation=recommendation,
        )

    # ======================================================
    # DISCOVERY SIGNALS
    # ======================================================

    def _apply_discovery_signals(
        self,
        reasons,
        discovery: dict,
    ):
        """
        Convert verified affiliate discovery data into
        deterministic scoring signals.
        """

        # --------------------------------------------------
        # Affiliate program confirmed
        # --------------------------------------------------

        if self._program_verified(
            discovery
        ):

            reasons.append(
                self._reason(
                    "Affiliate Program Verified",
                    20,
                    (
                        "An affiliate program was "
                        "identified and supported by "
                        "website evidence."
                    ),
                )
            )

        elif self._program_likely(
            discovery
        ):

            reasons.append(
                self._reason(
                    "Affiliate Program Likely",
                    10,
                    (
                        "Website research indicates "
                        "a likely affiliate program, "
                        "but verification is incomplete."
                    ),
                )
            )

        else:

            reasons.append(
                self._reason(
                    "Affiliate Program Requires Verification",
                    0,
                    (
                        "Affiliate-program availability "
                        "could not be verified."
                    ),
                )
            )

        # --------------------------------------------------
        # Commission
        # --------------------------------------------------

        commission_type = str(
            discovery.get(
                "commission_type",
                "",
            )
        ).strip()

        commission_estimate = str(
            discovery.get(
                "commission_estimate",
                "",
            )
        ).strip()

        commission_text = (
            f"{commission_type} "
            f"{commission_estimate}"
        ).lower()

        if self._commission_verified(
            discovery
        ):

            commission_points = 15

            if (
                "recurring"
                in commission_text
            ):

                commission_points = 20

            reasons.append(
                self._reason(
                    "Commission Verified",
                    commission_points,
                    (
                        "The affiliate discovery "
                        "evidence contains commission "
                        "information."
                    ),
                )
            )

        else:

            reasons.append(
                self._reason(
                    "Commission Requires Verification",
                    0,
                    (
                        "Affiliate commission information "
                        "has not been confirmed."
                    ),
                )
            )

        # --------------------------------------------------
        # Cookie window
        # --------------------------------------------------

        cookie_window = str(
            discovery.get(
                "cookie_window",
                "",
            )
        ).strip()

        cookie_days = self._extract_days(
            cookie_window
        )

        if cookie_days >= 180:

            reasons.append(
                self._reason(
                    "Long Cookie Window",
                    10,
                    (
                        f"The affiliate program provides "
                        f"a {cookie_window} cookie window."
                    ),
                )
            )

        elif cookie_days >= 90:

            reasons.append(
                self._reason(
                    "Strong Cookie Window",
                    7,
                    (
                        f"The affiliate program provides "
                        f"a {cookie_window} cookie window."
                    ),
                )
            )

        elif cookie_days > 0:

            reasons.append(
                self._reason(
                    "Cookie Window Verified",
                    5,
                    (
                        f"The affiliate program provides "
                        f"a {cookie_window} cookie window."
                    ),
                )
            )

        # --------------------------------------------------
        # Affiliate platform
        # --------------------------------------------------

        platform = str(
            discovery.get(
                "affiliate_platform",
                "",
            )
        ).strip()

        if platform:

            reasons.append(
                self._reason(
                    "Affiliate Platform Identified",
                    5,
                    (
                        f"The affiliate program is "
                        f"associated with {platform}."
                    ),
                )
            )

    # ======================================================
    # PROGRAM CHECKS
    # ======================================================

    @staticmethod
    def _program_verified(
        discovery: dict | None,
    ) -> bool:

        if not discovery:

            return False

        found = discovery.get(
            "affiliate_program_found"
        )

        likely = str(
            discovery.get(
                "affiliate_program_likely",
                "",
            )
        ).strip().lower()

        return (
            found is True
            or likely in {
                "yes",
                "true",
                "confirmed",
                "verified",
            }
        )

    @staticmethod
    def _program_likely(
        discovery: dict,
    ) -> bool:

        likely = str(
            discovery.get(
                "affiliate_program_likely",
                "",
            )
        ).strip().lower()

        return likely in {
            "yes",
            "likely",
            "probable",
        }

    # ======================================================
    # COMMISSION CHECK
    # ======================================================

    @staticmethod
    def _commission_verified(
        discovery: dict,
    ) -> bool:

        values = [

            discovery.get(
                "commission_type"
            ),

            discovery.get(
                "commission_estimate"
            ),

        ]

        for value in values:

            if value is None:

                continue

            text = str(
                value
            ).strip().lower()

            if not text:

                continue

            if text in {
                "unknown",
                "none",
                "n/a",
                "not specified",
                "not available",
            }:

                continue

            return True

        # Also inspect evidence because the discovery
        # service may have found commission information
        # but not yet normalized it into the fields.

        evidence = discovery.get(
            "evidence",
            [],
        )

        if isinstance(
            evidence,
            list,
        ):

            combined = " ".join(
                str(item)
                for item in evidence
            ).lower()

            commission_terms = (
                "commission",
                "recurring commission",
                "monthly recurring",
                "payout",
            )

            for term in commission_terms:

                if term in combined:

                    return True

        return False

    # ======================================================
    # RECOMMENDATION
    # ======================================================

    @staticmethod
    def _build_verified_recommendation(
        analysis: AffiliateAnalysis,
        discovery: dict,
    ) -> str:

        company = (
            analysis.company
            or "This company"
        )

        commission = str(
            discovery.get(
                "commission_estimate",
                "",
            )
        ).strip()

        commission_type = str(
            discovery.get(
                "commission_type",
                "",
            )
        ).strip()

        cookie_window = str(
            discovery.get(
                "cookie_window",
                "",
            )
        ).strip()

        platform = str(
            discovery.get(
                "affiliate_platform",
                "",
            )
        ).strip()

        details = []

        if commission:
            details.append(
                f"commission: {commission}"
            )

        elif commission_type:
            details.append(
                f"commission type: {commission_type}"
            )

        if cookie_window:
            details.append(
                f"cookie window: {cookie_window}"
            )

        if platform:
            details.append(
                f"platform: {platform}"
            )

        if details:

            detail_text = (
                "; ".join(details)
            )

            return (
                f"{company} has a verified affiliate "
                f"opportunity supported by website "
                f"research ({detail_text}). "
                f"The opportunity should be evaluated "
                f"for content fit, competition, audience "
                f"quality, and expected conversion potential."
            )

        return (
            f"{company} has a verified affiliate "
            f"opportunity supported by website research. "
            f"The opportunity should be evaluated for "
            f"content fit, competition, audience quality, "
            f"and expected conversion potential."
        )

    # ======================================================
    # HELPERS
    # ======================================================

    @staticmethod
    def _reason(
        title: str,
        points: int,
        description: str,
    ):
        """
        Create a scoring reason using the same structure
        expected by IntelligenceResult.
        """

        # Import locally so this scoring module remains
        # compatible with the existing rules implementation.
        from app.intelligence.models import IntelligenceReason

        return IntelligenceReason(
            title=title,
            points=points,
            description=description,
        )

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0

    @staticmethod
    def _extract_days(
        value: str,
    ) -> int:

        import re

        match = re.search(
            r"(\d+)",
            value,
        )

        if not match:

            return 0

        try:

            return int(
                match.group(1)
            )

        except ValueError:

            return 0