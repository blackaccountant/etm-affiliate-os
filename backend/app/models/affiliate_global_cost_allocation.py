"""Append-only batches and lines for explicit global-cost allocation authority."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


def _new_id() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AffiliateGlobalCostAllocationBatch(Base):
    __tablename__ = "affiliate_global_cost_allocation_batches"
    __table_args__ = (
        UniqueConstraint(
            "affiliate_cost_event_id",
            name="uq_affiliate_global_cost_allocation_batches_cost",
        ),
        UniqueConstraint(
            "source_namespace",
            "source_event_digest",
            name="uq_affiliate_global_cost_allocation_batches_source",
        ),
        CheckConstraint(
            "allocated_amount > 0",
            name="ck_affiliate_global_cost_allocation_batches_positive",
        ),
        CheckConstraint(
            column("fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_affiliate_global_cost_allocation_batches_fingerprint",
        ),
        CheckConstraint(
            column("source_event_digest").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_affiliate_global_cost_allocation_batches_source_digest",
        ),
        CheckConstraint(
            column("source_namespace").regexp_match(r"^[a-z][a-z0-9.-]{0,62}$"),
            name="ck_affiliate_global_cost_allocation_batches_namespace",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_id,
    )
    affiliate_cost_event_id: Mapped[str] = mapped_column(
        ForeignKey("affiliate_cost_events.id"),
        nullable=False,
    )
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
    )


class AffiliateGlobalCostAllocationLine(Base):
    __tablename__ = "affiliate_global_cost_allocation_lines"
    __table_args__ = (
        UniqueConstraint(
            "allocation_batch_id",
            "affiliate_earning_id",
            name="uq_affiliate_global_cost_allocation_lines_target",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_affiliate_global_cost_allocation_lines_positive",
        ),
        CheckConstraint(
            column("fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_affiliate_global_cost_allocation_lines_fingerprint",
        ),
        Index(
            "ix_affiliate_global_cost_allocation_lines_earning",
            "affiliate_earning_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_id,
    )
    allocation_batch_id: Mapped[str] = mapped_column(
        ForeignKey("affiliate_global_cost_allocation_batches.id"),
        nullable=False,
    )
    affiliate_earning_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_earnings.id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
    )
