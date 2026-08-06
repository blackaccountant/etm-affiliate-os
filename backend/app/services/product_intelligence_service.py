"""
Product Intelligence Service
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.intelligence.models import IntelligenceResult
from app.repositories.product_repository import ProductRepository
from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.workflows.core.workflow_result import DatabaseResult


class ProductIntelligenceService:

    def __init__(self, db: Session):

        self.repository = ProductRepository(db)

    def save_analysis(
        self,
        analysis: AffiliateAnalysis,
        intelligence: IntelligenceResult,
    ) -> DatabaseResult:

        existing = self.repository.get_by_website(
            analysis.website
        )

        if existing:

            return DatabaseResult(
                saved=False,
                duplicate=True,
                product_id=existing.id,
                message="Product already exists.",
            )

        product = self.repository.create_from_analysis(
            analysis,
            intelligence,
        )

        return DatabaseResult(
            saved=True,
            duplicate=False,
            product_id=product.id,
            message="Product saved successfully.",
        )