"""
Affiliate Intelligence Weights

Defines the scoring weights used by the
Affiliate Intelligence Engine.
"""

from __future__ import annotations

from app.intelligence.models import IntelligenceWeights

# Default scoring weights
DEFAULT_WEIGHTS = IntelligenceWeights()

# Grade thresholds
GRADE_A = 90
GRADE_B = 75
GRADE_C = 60
GRADE_D = 40

# Confidence thresholds
HIGH_CONFIDENCE = 90
MEDIUM_CONFIDENCE = 75
LOW_CONFIDENCE = 50