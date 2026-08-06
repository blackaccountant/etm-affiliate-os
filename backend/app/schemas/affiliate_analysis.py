"""
Affiliate Analysis Schema

Represents structured intelligence returned by the AI
after analyzing a company's website.
"""

from typing import List

from pydantic import BaseModel, Field


class AffiliateAnalysis(BaseModel):
    """
    Structured affiliate intelligence.
    """

    company: str = Field(
        description="Company name"
    )

    website: str = Field(
        description="Official website"
    )

    category: str = Field(
        description="Product category"
    )

    summary: str = Field(
        description="Short business summary"
    )

    target_audience: List[str] = Field(
        default_factory=list
    )

    pricing_model: str = Field(
        default=""
    )

    affiliate_program_likely: str = Field(
        default=""
    )

    commission_type: str = Field(
        default=""
    )

    commission_estimate: str = Field(
        default=""
    )

    affiliate_score: int = Field(
        ge=0,
        le=100,
        default=0,
    )

    recommendation: str = Field(
        default=""
    )