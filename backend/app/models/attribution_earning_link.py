"""Immutable, reference-only M10A4 continuation from conversion fact to earning."""

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


class AttributionEarningLink(Base):
    __tablename__ = "attribution_earning_links"
    __table_args__ = (
        UniqueConstraint("attribution_fact_id", name="uq_attribution_earning_links_fact"),
        UniqueConstraint("affiliate_conversion_id", name="uq_attribution_earning_links_conversion"),
        UniqueConstraint("affiliate_earning_id", name="uq_attribution_earning_links_earning"),
        UniqueConstraint(
            "source_namespace", "source_event_key_digest",
            name="uq_attribution_earning_links_source",
        ),
        CheckConstraint(
            column("linkage_fingerprint").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_attribution_earning_links_fingerprint",
        ),
        CheckConstraint(
            column("source_event_key_digest").regexp_match(r"^[0-9a-f]{64}$"),
            name="ck_attribution_earning_links_source_digest",
        ),
        CheckConstraint(
            column("source_namespace").regexp_match(r"^[a-z][a-z0-9.-]{0,62}$"),
            name="ck_attribution_earning_links_namespace",
        ),
        Index("ix_attribution_earning_links_earning", "affiliate_earning_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    attribution_fact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attribution_facts.id"), nullable=False,
    )
    affiliate_conversion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("affiliate_conversions.id"), nullable=False,
    )
    affiliate_earning_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("affiliate_earnings.id"), nullable=False,
    )
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    linkage_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utc_now)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utc_now)
