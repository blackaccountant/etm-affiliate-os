"""
Affiliate Conversion Model

Represents a conversion attributed to an affiliate program
and/or affiliate link.

Business rule:

    One external conversion ID
    must only exist once per affiliate program.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.database.base import Base


class AffiliateConversion(Base):

    __tablename__ = "affiliate_conversions"

    __table_args__ = (
        UniqueConstraint(
            "affiliate_program_id",
            "external_conversion_id",
            name="uq_affiliate_conversion_external_id",
        ),
    )

    # =========================================================
    # Identity
    # =========================================================

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # Attribution
    # =========================================================

    affiliate_link_id = Column(
        Integer,
        ForeignKey(
            "affiliate_links.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    affiliate_program_id = Column(
        Integer,
        ForeignKey(
            "affiliate_programs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # =========================================================
    # External Identity / Idempotency
    # =========================================================

    external_conversion_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    customer_reference = Column(
        String(255),
        nullable=True,
    )

    # =========================================================
    # Sale
    # =========================================================

    sale_amount = Column(
        Numeric(
            precision=14,
            scale=2,
        ),
        nullable=False,
        default=0,
    )

    currency = Column(
        String(10),
        nullable=False,
        default="USD",
    )

    # =========================================================
    # Conversion Lifecycle
    # =========================================================

    conversion_status = Column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )

    # =========================================================
    # Commission
    # =========================================================

    commission_rate = Column(
        Numeric(
            precision=10,
            scale=4,
        ),
        nullable=True,
    )

    commission_amount = Column(
        Numeric(
            precision=14,
            scale=2,
        ),
        nullable=False,
        default=0,
    )

    # =========================================================
    # Source / Metadata
    # =========================================================

    source = Column(
        String(100),
        nullable=False,
        default="manual",
    )

    metadata_json = Column(
        Text,
        nullable=True,
    )

    # =========================================================
    # Timestamps
    # =========================================================

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )