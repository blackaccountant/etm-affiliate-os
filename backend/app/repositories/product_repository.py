"""
ETM Affiliate OS
Product Repository

Database access layer for Product operations.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.product import Product


class ProductRepository:

    def __init__(self, db: Session):
        self.db = db

    # =========================================================
    # CREATE
    # =========================================================

    def create(
        self,
        product: Product,
    ) -> Product:

        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)

        return product

    # =========================================================
    # CREATE FROM AI ANALYSIS
    # =========================================================

    def create_from_analysis(
        self,
        analysis: dict,
        website: str,
    ) -> Product:

        product = Product(
            name=analysis.get("name"),
            website=website,
            category=analysis.get("category"),
            affiliate_program=analysis.get(
                "affiliate_program"
            ),
            affiliate_url=analysis.get(
                "affiliate_url"
            ),
            commission_type=analysis.get(
                "commission_type"
            ),
            commission_value=analysis.get(
                "commission_value"
            ),
            cookie_duration=analysis.get(
                "cookie_duration"
            ),
            affiliate_score=analysis.get(
                "score",
                0,
            ),
            grade=analysis.get(
                "grade",
                "F",
            ),
            confidence=analysis.get(
                "confidence",
                0,
            ),
            summary=analysis.get(
                "summary",
                "",
            ),
            recommendation=analysis.get(
                "recommendation",
                "",
            ),
            status="active",
        )

        return self.create(product)

    # =========================================================
    # READ
    # =========================================================

    def get_by_id(
        self,
        product_id: int,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

    def get_all(self):

        return (
            self.db.query(Product)
            .order_by(Product.id.asc())
            .all()
        )

    def get_by_name(
        self,
        name: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(Product.name == name)
            .first()
        )

    def get_by_website(
        self,
        website: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(Product.website == website)
            .first()
        )

    def get_by_affiliate_url(
        self,
        affiliate_url: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(
                Product.affiliate_url == affiliate_url
            )
            .first()
        )

    # =========================================================
    # EXISTENCE CHECKS
    # =========================================================

    def exists_by_name(
        self,
        name: str,
    ) -> bool:

        return (
            self.db.query(Product)
            .filter(
                Product.name == name
            )
            .first()
            is not None
        )

    def exists_by_website(
        self,
        website: str,
    ) -> bool:

        return (
            self.db.query(Product)
            .filter(
                Product.website == website
            )
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
                Product.affiliate_url == affiliate_url
            )
            .first()
            is not None
        )

    # =========================================================
    # UPDATE
    # =========================================================

    def update(
        self,
        product: Product,
        update_data: Any,
    ) -> Product:

        """
        Update an existing Product.

        Supports both:

        - Pydantic ProductUpdate objects
        - dictionaries

        The service layer currently passes a ProductUpdate
        object, so we convert it to a dictionary here.
        """

        # -----------------------------------------------------
        # Convert Pydantic model to dictionary
        # -----------------------------------------------------

        if hasattr(update_data, "model_dump"):
            data = update_data.model_dump(
                exclude_unset=True,
                exclude_none=True,
            )

        elif hasattr(update_data, "dict"):
            data = update_data.dict(
                exclude_unset=True,
                exclude_none=True,
            )

        elif isinstance(update_data, dict):
            data = {
                key: value
                for key, value in update_data.items()
                if value is not None
            }

        else:
            raise TypeError(
                "update_data must be a dictionary "
                "or a Pydantic model."
            )

        # -----------------------------------------------------
        # Apply updates
        # -----------------------------------------------------

        for field, value in data.items():

            if hasattr(Product, field):
                setattr(
                    product,
                    field,
                    value,
                )

        # -----------------------------------------------------
        # Persist changes
        # -----------------------------------------------------

        self.db.commit()
        self.db.refresh(product)

        return product

    # =========================================================
    # DELETE
    # =========================================================

    def delete(
        self,
        product: Product,
    ) -> None:

        self.db.delete(product)
        self.db.commit()