"""
Affiliate Intelligence Scoring Engine
"""

from __future__ import annotations

from app.intelligence.models import (
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
    Scores affiliate opportunities using
    deterministic business rules.
    """

    def __init__(self):
        self.rules = AffiliateRules()

    def score(
        self,
        analysis: AffiliateAnalysis,
    ) -> IntelligenceResult:

        reasons = self.rules.evaluate(analysis)

        total = sum(
            reason.points
            for reason in reasons
        )

        score = min(total, 100)

        # -------------------------
        # Grade
        # -------------------------

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

        # -------------------------
        # Confidence
        # -------------------------

        confidence = min(
            50 + (len(reasons) * 10),
            100,
        )

        return IntelligenceResult(
            score=score,
            grade=grade,
            confidence=confidence,
            reasons=reasons,
            summary=analysis.summary,
            recommendation=analysis.recommendation,
        )