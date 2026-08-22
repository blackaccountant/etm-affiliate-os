"""
Affiliate Earning Model

Represents commission earned from an affiliate conversion.

Business rule:

    One conversion
        ↓
    One earning

The database enforces this relationship with a UNIQUE
constraint on conversion_id.

An earning may later be attached to one affiliate payout.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.database.base import Base


class AffiliateEarning(Base):

    __tablename__ = "affiliate_earnings"

    __table_args__ = (
        UniqueConstraint(
            "conversion_id",
            name="uq_affiliate_earning_conversion_id",
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
    # Source Conversion
    # =========================================================

    conversion_id = Column(
        Integer,
        ForeignKey(
            "affiliate_conversions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # =========================================================
    # Affiliate Program
    # =========================================================

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
    # Financial Information
    # =========================================================

    gross_amount = Column(
        Numeric(
            precision=18,
            scale=2,
        ),
        nullable=False,
    )

    commission_rate = Column(
        Numeric(
            precision=10,
            scale=4,
        ),
        nullable=False,
    )

    commission_amount = Column(
        Numeric(
            precision=18,
            scale=2,
        ),
        nullable=False,
    )

    currency = Column(
        String(10),
        nullable=False,
        default="USD",
    )

    # =========================================================
    # Earning Lifecycle
    # =========================================================

    status = Column(
        String(30),
        nullable=False,
        default="approved",
        index=True,
    )

    # =========================================================
    # Payout Information
    # =========================================================

    payout_reference = Column(
        String(255),
        nullable=True,
    )

    paid_at = Column(
        DateTime,
        nullable=True,
    )

    payout_id = Column(
        Integer,
        ForeignKey(
            "affiliate_payouts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
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