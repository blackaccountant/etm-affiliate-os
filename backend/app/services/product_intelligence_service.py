"""
Product Intelligence Service

Persists affiliate product intelligence
and maintains historical intelligence snapshots.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.intelligence.models import IntelligenceResult
from app.repositories.product_repository import ProductRepository
from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.workflows.core.workflow_result import DatabaseResult
from app.models.product_intelligence_history import (
    ProductIntelligenceHistory,
)


class ProductIntelligenceService:

    def __init__(
        self,
        db: Session,
    ):

        self.db = db

        self.repository = ProductRepository(
            db
        )


    def save_analysis(
        self,
        analysis: AffiliateAnalysis,
        intelligence: IntelligenceResult,
    ) -> DatabaseResult:

        existing = self.repository.get_by_website(
            analysis.website
        )


        # ==================================================
        # Existing Product
        # ==================================================

        if existing:

            history = ProductIntelligenceHistory(

                product_id=existing.id,

                score=intelligence.score,

                grade=intelligence.grade,

                confidence=intelligence.confidence,

                recommendation=intelligence.recommendation,

            )

            self.db.add(
                history
            )

            self.db.commit()


            return DatabaseResult(

                saved=False,

                duplicate=True,

                product_id=existing.id,

                message=(
                    "Product already exists. "
                    "Intelligence history recorded."
                ),

            )


        # ==================================================
        # New Product
        # ==================================================

        product = self.repository.create_from_analysis(
            analysis,
            intelligence,
        )


        history = ProductIntelligenceHistory(

            product_id=product.id,

            score=intelligence.score,

            grade=intelligence.grade,

            confidence=intelligence.confidence,

            recommendation=intelligence.recommendation,

        )

        self.db.add(
            history
        )

        self.db.commit()


        return DatabaseResult(

            saved=True,

            duplicate=False,

            product_id=product.id,

            message=(
                "Product saved successfully "
                "and intelligence history recorded."
            ),

        )