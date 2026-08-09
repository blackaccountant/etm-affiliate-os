"""
Product Repository

Handles persistence and retrieval of affiliate product intelligence.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.intelligence.models import IntelligenceResult
from app.models.product import Product
from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.schemas.product import ProductCreate, ProductUpdate


class ProductRepository:
    """
    Repository for Product operations.
    """

    def __init__(self, db: Session):
        self.db = db

    # ==========================================================
    # Intelligence lookup
    # ==========================================================

    def get_by_website(
        self,
        website: str,
    ) -> Product | None:

        return (
            self.db.query(Product)
            .filter(Product.website == website)
            .first()
        )

    # ==========================================================
    # CRUD - Create
    # ==========================================================

    def create(
        self,
        product_data: ProductCreate,
    ) -> Product:

        product = Product(
            name=product_data.name,
            website=str(product_data.website),
            category=product_data.category,

            affiliate_program=(
                product_data.affiliate_program
            ),

            affiliate_url=(
                str(product_data.affiliate_url)
                if product_data.affiliate_url
                else None
            ),

            commission_type=(
                product_data.commission_type
            ),

            commission_value=(
                product_data.commission_value
            ),

            cookie_duration=(
                product_data.cookie_duration
                if product_data.cookie_duration
                else None
            ),

            status=product_data.status,
        )

        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)

        return product

    # ==========================================================
    # Intelligence create
    # ==========================================================

    def create_from_analysis(
        self,
        analysis: AffiliateAnalysis,
        intelligence: IntelligenceResult,
    ) -> Product:

        product = Product(
            name=analysis.company,
            website=analysis.website,
            category=analysis.category,

            affiliate_program=(
                analysis.affiliate_program_likely
            ),

            affiliate_url=None,

            commission_type=(
                analysis.commission_type
            ),

            commission_value=(
                analysis.commission_estimate
            ),

            cookie_duration=None,

            affiliate_score=intelligence.score,
            grade=intelligence.grade,
            confidence=intelligence.confidence,

            summary=intelligence.summary,

            recommendation=(
                intelligence.recommendation
            ),

            status="active",
        )

        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)

        return product

    # ==========================================================
    # CRUD - Read
    # ==========================================================

    def get_all(self) -> List[Product]:

        return (
            self.db.query(Product)
            .order_by(Product.created_at.desc())
            .all()
        )

    def get_by_id(
        self,
        product_id: int,
    ) -> Product | None:

        return (
            self.db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

    # ==========================================================
    # CRUD - Update
    # ==========================================================

    def update(
        self,
        product: Product,
        product_update: ProductUpdate,
    ) -> Product:

        update_data = product_update.model_dump(
            exclude_unset=True,
            exclude_none=True,
        )

        for field, value in update_data.items():

            if field in {
                "website",
                "affiliate_url",
            }:

                value = str(value)

            setattr(
                product,
                field,
                value,
            )

        self.db.commit()
        self.db.refresh(product)

        return product

    # ==========================================================
    # CRUD - Delete
    # ==========================================================

    def delete(
        self,
        product: Product,
    ) -> None:

        self.db.delete(product)

        self.db.commit()

    # ==========================================================
    # Duplicate helpers
    # ==========================================================

    def exists_by_name(
        self,
        name: str,
    ) -> bool:

        return (
            self.db.query(Product)
            .filter(Product.name == name)
            .first()
            is not None
        )

    def exists_by_affiliate_url(
        self,
        affiliate_url: str,
    ) -> bool:

        return (
            self.db.query(Product)
            .filter(
                Product.affiliate_url
                == affiliate_url
            )
            .first()
            is not None
        )