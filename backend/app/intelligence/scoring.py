"""
Affiliate Intelligence Scoring Engine

Combines commercial opportunity scoring with
affiliate discovery evidence.

The scoring engine remains deterministic.

Architecture:

1. AffiliateRules
   -> commercial attractiveness

2. AffiliateDiscoveryService
   -> affiliate monetization evidence

3. AffiliateScoringEngine
   -> combined opportunity score

Discovery evidence is not allowed to double-count
commercial signals.
"""

from __future__ import annotations

from app.intelligence.models import (
    IntelligenceReason,
    IntelligenceResult,
)
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
    commercial rules plus verified affiliate discovery
    evidence.
    """

    def __init__(self):
        self.rules = AffiliateRules()

    # ======================================================
    # PUBLIC SCORING
    # ======================================================

    def score(
        self,
        analysis: AffiliateAnalysis,
        discovery: dict | None = None,
    ) -> IntelligenceResult:
        """
        Score an affiliate opportunity.

        Commercial attractiveness is calculated from
        AffiliateRules.

        Affiliate-program and monetization evidence
        is calculated from discovery data.
        """

        # ==================================================
        # STEP 1 — COMMERCIAL RULES
        # ==================================================

        reasons = list(
            self.rules.evaluate(
                analysis
            )
        )

        # ==================================================
        # STEP 2 — DISCOVERY SIGNALS
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

        confidence = self._calculate_confidence(
            reasons,
            discovery,
        )

        # ==================================================
        # STEP 6 — RECOMMENDATION
        # ==================================================

        recommendation = (
            analysis.recommendation
        )

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
        reasons: list[IntelligenceReason],
        discovery: dict,
    ) -> None:
        """
        Convert affiliate discovery evidence into
        deterministic scoring signals.

        Only meaningful positive discovery signals
        are added.

        Unknown information does not generate a
        zero-point reason.
        """

        # --------------------------------------------------
        # Affiliate Program
        # --------------------------------------------------

        if self._program_verified(
            discovery
        ):
            reasons.append(
                self._reason(
                    "Affiliate Program Verified",
                    20,
                    (
                        "Website research provides "
                        "strong evidence supporting "
                        "an affiliate program."
                    ),
                )
            )

        elif self._program_likely(
            discovery
        ):
            reasons.append(
                self._reason(
                    "Affiliate Program Likely",
                    8,
                    (
                        "Website research suggests "
                        "an affiliate opportunity, "
                        "but verification is incomplete."
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

            if "recurring" in commission_text:
                commission_points = 20

            reasons.append(
                self._reason(
                    "Commission Verified",
                    commission_points,
                    (
                        "Affiliate discovery evidence "
                        "contains identifiable commission "
                        "information."
                    ),
                )
            )

        # --------------------------------------------------
        # Cookie Window
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
        # Affiliate Platform
        # --------------------------------------------------

        platform = str(
            discovery.get(
                "affiliate_platform",
                "",
            )
        ).strip()

        if platform and platform.lower() not in {
            "unknown",
            "none",
            "n/a",
        }:
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
    # CONFIDENCE
    # ======================================================

    def _calculate_confidence(
        self,
        reasons: list[IntelligenceReason],
        discovery: dict | None,
    ) -> int:
        """
        Calculate confidence from evidence quality.

        Confidence is intentionally separate from
        opportunity score.

        A high score with weak evidence can therefore
        have lower confidence.
        """

        commercial_reasons = [
            reason
            for reason in reasons
            if reason.title
            not in {
                "Affiliate Program Verified",
                "Affiliate Program Likely",
                "Commission Verified",
                "Long Cookie Window",
                "Strong Cookie Window",
                "Cookie Window Verified",
                "Affiliate Platform Identified",
            }
        ]

        discovery_reasons = [
            reason
            for reason in reasons
            if reason.title
            in {
                "Affiliate Program Verified",
                "Affiliate Program Likely",
                "Commission Verified",
                "Long Cookie Window",
                "Strong Cookie Window",
                "Cookie Window Verified",
                "Affiliate Platform Identified",
            }
        ]

        # --------------------------------------------------
        # Commercial evidence
        # --------------------------------------------------

        commercial_count = len(
            commercial_reasons
        )

        if commercial_count == 0:
            commercial_confidence = 30

        elif commercial_count == 1:
            commercial_confidence = 40

        elif commercial_count == 2:
            commercial_confidence = 50

        elif commercial_count == 3:
            commercial_confidence = 60

        elif commercial_count == 4:
            commercial_confidence = 65

        else:
            commercial_confidence = 70

        # --------------------------------------------------
        # Discovery evidence
        # --------------------------------------------------

        discovery_confidence = 0

        if discovery is not None:

            raw_discovery_confidence = (
                self._safe_int(
                    discovery.get(
                        "confidence"
                    )
                )
            )

            discovery_confidence = max(
                min(
                    raw_discovery_confidence,
                    100,
                ),
                0,
            )

        # --------------------------------------------------
        # Combine evidence
        # --------------------------------------------------

        if discovery is None:
            confidence = commercial_confidence

        elif discovery_confidence == 0:
            confidence = min(
                commercial_confidence,
                70,
            )

        elif discovery_confidence < 60:
            confidence = round(
                (
                    commercial_confidence * 0.70
                )
                + (
                    discovery_confidence * 0.30
                )
            )

        else:
            confidence = round(
                (
                    commercial_confidence * 0.50
                )
                + (
                    discovery_confidence * 0.50
                )
            )

        # Discovery evidence should provide a small
        # additional boost when multiple independent
        # signals exist.

        if len(discovery_reasons) >= 4:
            confidence += 10

        elif len(discovery_reasons) >= 2:
            confidence += 5

        return max(
            min(confidence, 100),
            0,
        )

    # ======================================================
    # PROGRAM CHECKS
    # ======================================================

    @staticmethod
    def _program_verified(
        discovery: dict | None,
    ) -> bool:
        """
        Determine whether discovery provides strong
        affiliate-program verification.
        """

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
        discovery: dict | None,
    ) -> bool:
        """
        Determine whether discovery suggests an
        affiliate program without full verification.
        """

        if not discovery:
            return False

        likely = str(
            discovery.get(
                "affiliate_program_likely",
                "",
            )
        ).strip().lower()

        return likely in {
            "likely",
            "probable",
        }

    # ======================================================
    # COMMISSION CHECK
    # ======================================================

    @staticmethod
    def _commission_verified(
        discovery: dict | None,
    ) -> bool:
        """
        Determine whether commission information
        has been identified.
        """

        if not discovery:
            return False

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

            return any(
                term in combined
                for term in commission_terms
            )

        return False

    # ======================================================
    # RECOMMENDATION
    # ======================================================

    @staticmethod
    def _build_verified_recommendation(
        analysis: AffiliateAnalysis,
        discovery: dict,
    ) -> str:
        """
        Build a recommendation based on verified
        affiliate discovery evidence.
        """

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

        if (
            commission
            and commission.lower()
            not in {
                "unknown",
                "none",
                "n/a",
            }
        ):
            details.append(
                f"commission: {commission}"
            )

        elif (
            commission_type
            and commission_type.lower()
            not in {
                "unknown",
                "none",
                "n/a",
            }
        ):
            details.append(
                f"commission type: {commission_type}"
            )

        if (
            cookie_window
            and cookie_window.lower()
            not in {
                "unknown",
                "none",
                "n/a",
            }
        ):
            details.append(
                f"cookie window: {cookie_window}"
            )

        if (
            platform
            and platform.lower()
            not in {
                "unknown",
                "none",
                "n/a",
            }
        ):
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
    ) -> IntelligenceReason:
        """
        Create an IntelligenceReason.
        """

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
