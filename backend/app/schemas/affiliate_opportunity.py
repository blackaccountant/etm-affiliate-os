"""
Affiliate Opportunity Schema

Defines AI-generated monetization strategy
for an affiliate product opportunity.
"""

from typing import List, Optional

from pydantic import BaseModel, Field



class AffiliateOpportunitySchema(BaseModel):

    opportunity_grade: str = Field(
        default="UNKNOWN"
    )


    audience: List[str] = Field(
        default_factory=list
    )


    content_strategy: List[str] = Field(
        default_factory=list
    )


    seo_keywords: List[str] = Field(
        default_factory=list
    )


    promotion_channels: List[str] = Field(
        default_factory=list
    )


    funnel_strategy: dict = Field(
        default_factory=dict
    )


    revenue_projection: dict = Field(
        default_factory=dict
    )


    ai_recommendation: str = ""


    confidence: int = 0