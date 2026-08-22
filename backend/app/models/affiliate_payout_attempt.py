"""
Affiliate Payout Attempt Model

Records individual attempts to settle an affiliate payout.

A single AffiliatePayout may have multiple attempts:

    Payout #3
        ├── Attempt #1 → failed
        └── Attempt #2 → succeeded

This preserves the payout obligation while maintaining an
audit trail of settlement attempts.
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


class AffiliatePayoutAttempt(Base):

    __tablename__ = "affiliate_payout_attempts"

    __table_args__ = (
        UniqueConstraint(
            "payout_id",
            "attempt_number",
            name="uq_affiliate_payout_attempt_payout_attempt_number",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    payout_id = Column(
        Integer,
        ForeignKey(
            "affiliate_payouts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    attempt_number = Column(
        Integer,
        nullable=False,
    )

    amount = Column(
        Numeric(
            precision=12,
            scale=2,
        ),
        nullable=False,
    )

    currency = Column(
        String(10),
        nullable=False,
        default="USD",
    )

    status = Column(
        String(50),
        nullable=False,
        default="processing",
        index=True,
    )

    provider = Column(
        String(100),
        nullable=True,
    )

    provider_reference = Column(
        String(255),
        nullable=True,
    )

    idempotency_key = Column(
        String(255),
        nullable=True,
        unique=True,
    )

    failure_reason = Column(
        Text,
        nullable=True,
    )

    started_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    completed_at = Column(
        DateTime,
        nullable=True,
    )

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