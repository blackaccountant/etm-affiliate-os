from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.database.base import Base
from app.models.product import Product


class AffiliateProgram(Base):
    """
    Affiliate Program Record

    Stores affiliate partnership information
    discovered for a product.
    """

    __tablename__ = "affiliate_programs"


    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )


    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )


    # ----------------------------
    # Program Identity
    # ----------------------------

    program_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )


    network: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )


    program_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )


    # ----------------------------
    # Commission
    # ----------------------------

    commission_type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    commission_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    cookie_duration: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )


    # ----------------------------
    # Verification
    # ----------------------------

    confidence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )


    evidence: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


    status: Mapped[str] = mapped_column(
        String(100),
        default="active",
        nullable=False,
    )


    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


    # Relationship

    product = relationship(
        "Product",
        back_populates="affiliate_programs",
    )