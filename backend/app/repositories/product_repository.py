"""
Product Repository

Handles persistence and retrieval of affiliate product intelligence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.intelligence.models import IntelligenceResult
from app.models.product import Product
from app.schemas.affiliate_analysis import AffiliateAnalysis


class ProductRepository:
    """
    Repository for Product operations.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_by_website(
        self,
        website: str,
    ) -> Product | None:

        return (
            self.db.query(Product)
            .filter(Product.website == website)
            .first()
        )

    def create_from_analysis(
        self,
        analysis: AffiliateAnalysis,
        intelligence: IntelligenceResult,
    ) -> Product:

        product = Product(
            name=analysis.company,
            website=analysis.website,
            category=analysis.category,

            affiliate_program=analysis.affiliate_program_likely,
            affiliate_url=None,

            commission_type=analysis.commission_type,
            commission_value=analysis.commission_estimate,
            cookie_duration=None,

            affiliate_score=intelligence.score,
            grade=intelligence.grade,
            confidence=intelligence.confidence,
            summary=intelligence.summary,
            recommendation=intelligence.recommendation,

            status="active",
        )

        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)

        return product