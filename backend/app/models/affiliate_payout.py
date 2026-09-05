"""
Affiliate Payout Model

Tracks settlement of affiliate earnings.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    Numeric,
    String,
    DateTime,
    ForeignKey,
)

from app.database.base import Base


class AffiliatePayout(Base):

    __tablename__ = "affiliate_payouts"


    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )


    affiliate_program_id = Column(
        Integer,
        ForeignKey("affiliate_programs.id"),
        nullable=False,
        index=True,
    )


    total_amount = Column(
        Numeric(
            precision=12,
            scale=2,
        ),
        nullable=False,
    )


    currency = Column(
        String(10),
        default="USD",
        nullable=False,
    )


    status = Column(
        String(50),
        default="pending",
        nullable=False,
    )


    payout_reference = Column(
        String(255),
        nullable=True,
    )


    paid_at = Column(
        DateTime,
        nullable=True,
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )