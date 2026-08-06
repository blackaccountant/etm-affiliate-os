"""
Workflow Result

Represents the outcome of a business workflow.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.intelligence.models import IntelligenceResult
from app.schemas.affiliate_analysis import AffiliateAnalysis


class DatabaseResult(BaseModel):
    """
    Database operation result.
    """

    saved: bool = False

    duplicate: bool = False

    product_id: int | None = None

    message: str = ""


class WorkflowResult(BaseModel):
    """
    Standard result returned by workflows.
    """

    analysis: AffiliateAnalysis

    intelligence: IntelligenceResult

    database: DatabaseResult

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )