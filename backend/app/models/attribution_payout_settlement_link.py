"""Immutable, reference-only M10A5 observation of successful payout settlement."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, column
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


def _new_id() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AttributionPayoutSettlementLink(Base):
    __tablename__ = "attribution_payout_settlement_links"
    __table_args__ = (
        UniqueConstraint(
            "attribution_earning_link_id", name="uq_attribution_payout_settlement_links_earning_link",
        ),
        UniqueConstraint(
            "affiliate_earning_id", name="uq_attribution_payout_settlement_links_earning",
        ),
        UniqueConstraint(
            "affiliate_earning_id", "affiliate_payout_id", "affiliate_payout_attempt_id",
            name="uq_attribution_payout_settlement_links_lineage",
        ),
        UniqueConstraint(
            "source_namespace", "source_event_key_digest",
            name="uq_attribution_payout_settlement_links_source",
        ),
        CheckConstraint(
            column("linkage_fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_attribution_payout_settlement_links_fingerprint",
        ),
        CheckConstraint(
            column("source_event_key_digest").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_attribution_payout_settlement_links_source_digest",
        ),
        CheckConstraint(
            column("source_namespace").regexp_match(r"^[a-z][a-z0-9.-]{0,62}$"),
            name="ck_attribution_payout_settlement_links_namespace",
        ),
        Index("ix_attribution_payout_settlement_links_payout", "affiliate_payout_id"),
        Index("ix_attribution_payout_settlement_links_attempt", "affiliate_payout_attempt_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    attribution_earning_link_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attribution_earning_links.id"), nullable=False,
    )
    affiliate_earning_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("affiliate_earnings.id"), nullable=False,
    )
    affiliate_payout_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("affiliate_payouts.id"), nullable=False,
    )
    affiliate_payout_attempt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("affiliate_payout_attempts.id"), nullable=False,
    )
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    linkage_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utc_now)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utc_now)
