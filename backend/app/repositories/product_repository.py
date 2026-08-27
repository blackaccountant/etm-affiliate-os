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

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    # =========================================================
    # CREATE
    # =========================================================

    def create(
        self,
        product: Product,
    ) -> Product:

        self.db.add(product)
        self.db.flush()
        self.db.refresh(product)

        return product

    # =========================================================
    # CREATE FROM INTELLIGENCE
    # =========================================================

    def create_from_analysis(
        self,
        analysis,
        intelligence,
    ) -> Product:
        """
        Create a Product from the current intelligence models.

        analysis:
            AffiliateAnalysis

        intelligence:
            IntelligenceResult

        Affiliate-program-specific information is persisted
        separately by ProductIntelligenceService through
        save_affiliate_program().
        """

        # -----------------------------------------------------
        # Read analysis values
        # -----------------------------------------------------

        company = getattr(
            analysis,
            "company",
            "",
        ) or ""

        website = getattr(
            analysis,
            "website",
            "",
        ) or ""

        category = getattr(
            analysis,
            "category",
            "",
        ) or ""

        summary = getattr(
            intelligence,
            "summary",
            "",
        ) or getattr(
            analysis,
            "summary",
            "",
        ) or ""

        recommendation = getattr(
            intelligence,
            "recommendation",
            "",
        ) or getattr(
            analysis,
            "recommendation",
            "",
        ) or ""

        # -----------------------------------------------------
        # Affiliate information
        # -----------------------------------------------------
        #
        # Discovery is the authoritative source for affiliate
        # program information, but the repository does not
        # receive discovery directly.
        #
        # Therefore these fields are initialized safely here.
        # ProductIntelligenceService.save_affiliate_program()
        # persists the detailed AffiliateProgram record.
        # -----------------------------------------------------

        affiliate_program_likely = getattr(
            analysis,
            "affiliate_program_likely",
            "",
        ) or ""

        commission_type = getattr(
            analysis,
            "commission_type",
            "",
        ) or ""

        commission_estimate = getattr(
            analysis,
            "commission_estimate",
            "",
        ) or ""

        # -----------------------------------------------------
        # Intelligence
        # -----------------------------------------------------

        score = int(
            getattr(
                intelligence,
                "score",
                0,
            )
            or 0
        )

        grade = getattr(
            intelligence,
            "grade",
            "F",
        ) or "F"

        confidence = int(
            getattr(
                intelligence,
                "confidence",
                0,
            )
            or 0
        )

        # -----------------------------------------------------
        # Required database fields
        # -----------------------------------------------------

        if not company:
            raise ValueError(
                "Affiliate analysis is missing company."
            )

        if not website:
            raise ValueError(
                "Affiliate analysis is missing website."
            )

        if not category:
            category = "Unknown"

        if not affiliate_program_likely:
            affiliate_program_likely = "Unknown"

        if not commission_type:
            commission_type = "Unknown"

        if not commission_estimate:
            commission_estimate = "Unknown"

        # -----------------------------------------------------
        # Create product
        # -----------------------------------------------------

        product = Product(

            name=company,

            website=website,

            category=category,

            affiliate_program=(
                affiliate_program_likely
            ),

            affiliate_url=None,

            commission_type=(
                commission_type
            ),

            commission_value=(
                commission_estimate
            ),

            cookie_duration=None,

            affiliate_score=score,

            grade=grade,

            confidence=confidence,

            summary=summary,

            recommendation=recommendation,

            status="active",

        )

        return self.create(
            product
        )

    # =========================================================
    # READ
    # =========================================================

    def get_by_id(
        self,
        product_id: int,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(
                Product.id == product_id
            )
            .first()
        )

    def get_all(
        self,
    ):

        return (
            self.db.query(Product)
            .order_by(
                Product.id.asc()
            )
            .all()
        )

    def get_by_name(
        self,
        name: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(
                Product.name == name
            )
            .first()
        )

    def get_by_website(
        self,
        website: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(
                Product.website == website
            )
            .first()
        )

    def get_by_affiliate_url(
        self,
        affiliate_url: str,
    ) -> Optional[Product]:

        return (
            self.db.query(Product)
            .filter(
                Product.affiliate_url
                == affiliate_url
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
                Product.affiliate_url
                == affiliate_url
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

        Supports:

        - Pydantic models
        - dictionaries
        """

        if hasattr(
            update_data,
            "model_dump",
        ):

            data = update_data.model_dump(
                exclude_unset=True,
                exclude_none=True,
            )

        elif hasattr(
            update_data,
            "dict",
        ):

            data = update_data.dict(
                exclude_unset=True,
                exclude_none=True,
            )

        elif isinstance(
            update_data,
            dict,
        ):

            data = {
                key: value
                for key, value
                in update_data.items()
                if value is not None
            }

        else:

            raise TypeError(
                "update_data must be a dictionary "
                "or a Pydantic model."
            )

        for field, value in data.items():

            if hasattr(
                Product,
                field,
            ):

                setattr(
                    product,
                    field,
                    value,
                )

        self.db.commit()

        self.db.refresh(
            product
        )

        return product

    # =========================================================
    # DELETE
    # =========================================================

    def delete(
        self,
        product: Product,
    ) -> None:

        self.db.delete(
            product
        )

        self.db.commit()