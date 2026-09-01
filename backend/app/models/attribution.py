"""Additive M10A attribution identities and immutable facts."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, column
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


_FACT_KINDS = "'PUBLICATION_BOUND','LINK_BOUND','CLICK_RECORDED','CONVERSION_REPORTED','ATTRIBUTION_CORRECTED'"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SOURCE_NAMESPACE_PATTERN = r"^[a-z][a-z0-9.-]{0,62}$"
_FACT_REFERENCES = """
(
 fact_kind = 'PUBLICATION_BOUND'
 AND attribution_publication_id IS NOT NULL
 AND attribution_context_id IS NULL AND attribution_click_id IS NULL
 AND affiliate_link_id IS NULL AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'LINK_BOUND'
 AND attribution_context_id IS NOT NULL AND affiliate_link_id IS NOT NULL
 AND attribution_publication_id IS NULL AND attribution_click_id IS NULL
 AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'CLICK_RECORDED'
 AND attribution_context_id IS NOT NULL AND attribution_click_id IS NOT NULL AND affiliate_link_id IS NOT NULL
 AND attribution_publication_id IS NULL AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'CONVERSION_REPORTED'
 AND attribution_context_id IS NOT NULL AND affiliate_conversion_id IS NOT NULL
 AND attribution_publication_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'ATTRIBUTION_CORRECTED' AND supersedes_fact_id IS NOT NULL
)
"""


class AttributionPublication(Base):
    __tablename__ = "attribution_publications"
    __table_args__ = (
        UniqueConstraint("legacy_publishing_queue_id", name="uq_attribution_publications_legacy_queue"),
        UniqueConstraint("distribution_run_id", name="uq_attribution_publications_distribution_run"),
        CheckConstraint(
            "(legacy_publishing_queue_id IS NOT NULL AND distribution_run_id IS NULL) OR "
            "(legacy_publishing_queue_id IS NULL AND distribution_run_id IS NOT NULL)",
            name="ck_attribution_publications_one_authority",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    legacy_publishing_queue_id: Mapped[int | None] = mapped_column(ForeignKey("publishing_queue.id"), nullable=True)
    distribution_run_id: Mapped[str | None] = mapped_column(ForeignKey("distribution_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AttributionContext(Base):
    __tablename__ = "attribution_contexts"
    __table_args__ = (
        UniqueConstraint("context_fingerprint", name="uq_attribution_contexts_fingerprint"),
        CheckConstraint(column("context_fingerprint").regexp_match(_SHA256_PATTERN), name="ck_attribution_contexts_fingerprint"),
        Index("ix_attribution_contexts_program", "affiliate_program_id"),
        Index("ix_attribution_contexts_publication", "attribution_publication_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    affiliate_program_id: Mapped[int] = mapped_column(ForeignKey("affiliate_programs.id"), nullable=False)
    attribution_publication_id: Mapped[str] = mapped_column(ForeignKey("attribution_publications.id"), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AttributionClick(Base):
    __tablename__ = "attribution_clicks"
    __table_args__ = (
        UniqueConstraint("click_key", name="uq_attribution_clicks_click_key"),
        UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_clicks_source"),
        CheckConstraint(column("source_fingerprint").regexp_match(_SHA256_PATTERN), name="ck_attribution_clicks_fingerprint"),
        CheckConstraint(column("source_event_key_digest").regexp_match(_SHA256_PATTERN), name="ck_attribution_clicks_source_digest"),
        CheckConstraint(column("source_namespace").regexp_match(_SOURCE_NAMESPACE_PATTERN), name="ck_attribution_clicks_namespace"),
        Index("ix_attribution_clicks_context", "attribution_context_id"),
        Index("ix_attribution_clicks_link", "affiliate_link_id"),
        Index("ix_attribution_clicks_occurred", "occurred_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    click_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attribution_context_id: Mapped[str] = mapped_column(ForeignKey("attribution_contexts.id"), nullable=False)
    affiliate_link_id: Mapped[int] = mapped_column(ForeignKey("affiliate_links.id"), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AttributionFact(Base):
    __tablename__ = "attribution_facts"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_facts_source"),
        CheckConstraint(f"fact_kind IN ({_FACT_KINDS})", name="ck_attribution_facts_kind"),
        CheckConstraint(_FACT_REFERENCES, name="ck_attribution_facts_references"),
        CheckConstraint(column("source_fingerprint").regexp_match(_SHA256_PATTERN), name="ck_attribution_facts_fingerprint"),
        CheckConstraint(column("source_event_key_digest").regexp_match(_SHA256_PATTERN), name="ck_attribution_facts_source_digest"),
        CheckConstraint(column("source_namespace").regexp_match(_SOURCE_NAMESPACE_PATTERN), name="ck_attribution_facts_namespace"),
        CheckConstraint("supersedes_fact_id IS NULL OR supersedes_fact_id <> id", name="ck_attribution_facts_no_self_supersede"),
        Index("ix_attribution_facts_kind_occurred", "fact_kind", "occurred_at"),
        Index("ix_attribution_facts_publication", "attribution_publication_id"),
        Index("ix_attribution_facts_context", "attribution_context_id"),
        Index("ix_attribution_facts_click", "attribution_click_id"),
        Index("ix_attribution_facts_link", "affiliate_link_id"),
        Index("ix_attribution_facts_conversion", "affiliate_conversion_id"),
        Index("ix_attribution_facts_supersedes", "supersedes_fact_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    source_event_key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attribution_publication_id: Mapped[str | None] = mapped_column(ForeignKey("attribution_publications.id"), nullable=True)
    attribution_context_id: Mapped[str | None] = mapped_column(ForeignKey("attribution_contexts.id"), nullable=True)
    attribution_click_id: Mapped[str | None] = mapped_column(ForeignKey("attribution_clicks.id"), nullable=True)
    affiliate_link_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_links.id"), nullable=True)
    affiliate_conversion_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_conversions.id"), nullable=True)
    supersedes_fact_id: Mapped[str | None] = mapped_column(ForeignKey("attribution_facts.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
