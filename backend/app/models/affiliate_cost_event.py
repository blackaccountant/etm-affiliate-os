"""Append-only authoritative operating cost events; never revenue adjustments."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


class AffiliateCostEvent(Base):
    __tablename__ = "affiliate_cost_events"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_digest", name="uq_affiliate_cost_events_source"),
        CheckConstraint("amount > 0", name="ck_affiliate_cost_events_positive_amount"),
        CheckConstraint("allocation_scope IN ('direct','shared','global')", name="ck_affiliate_cost_events_scope"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_type: Mapped[str] = mapped_column(String(63), nullable=False)
    allocation_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    affiliate_program_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_programs.id"), nullable=True)
    content_asset_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_content_assets.id"), nullable=True)
    content_generation_run_id: Mapped[str | None] = mapped_column(ForeignKey("content_generation_runs.id"), nullable=True)
    distribution_run_id: Mapped[str | None] = mapped_column(ForeignKey("distribution_runs.id"), nullable=True)
    affiliate_link_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_links.id"), nullable=True)
    affiliate_conversion_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_conversions.id"), nullable=True)
    affiliate_earning_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_earnings.id"), nullable=True)
    affiliate_payout_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_payouts.id"), nullable=True)
    affiliate_payout_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_payout_attempts.id"), nullable=True)
    outreach_provider_dispatch_id: Mapped[str | None] = mapped_column(ForeignKey("outreach_provider_dispatches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
