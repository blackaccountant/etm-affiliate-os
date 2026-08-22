"""
Intelligence Models

Core models used by the Intelligence Engine.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field



class IntelligenceReason(BaseModel):
    """
    A single scoring reason.
    """

    title: str

    points: int

    description: str


class IntelligenceResult(BaseModel):
    """
    Final intelligence score returned by the scoring engine.
    """

    score: int = Field(
        ge=0,
        le=100,
    )

    grade: str

    confidence: int = Field(
        ge=0,
        le=100,
    )

    reasons: List[IntelligenceReason] = Field(
        default_factory=list
    )

    summary: str = ""

    recommendation: str = ""


class IntelligenceWeights(BaseModel):
    """
    Configurable scoring weights.

    This allows different intelligence engines
    (Affiliate, VC, Real Estate, etc.)
    to reuse the same architecture.
    """

    official_affiliate_program: int = 25

    recurring_revenue: int = 20

    usage_based_pricing: int = 15

    subscription_pricing: int = 15

    global_market: int = 10

    developer_market: int = 10

    ai_category: int = 15

    high_ticket: int = 15

    free_trial: int = 5

    enterprise_market: int = 10