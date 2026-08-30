"""Additive M8C CRM qualification links and immutable lifecycle history."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class LeadQualificationLink(Base):
    __tablename__ = "crm_lead_qualification_links"
    __table_args__ = (
        UniqueConstraint("lead_id", "assessment_id", name="uq_crm_lead_qualification_links_identity"),
        Index("ix_crm_lead_qualification_links_assessment", "assessment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("audience_qualification_assessments.id"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    lead = relationship("Lead")
    assessment = relationship("AudienceQualificationAssessment")


class LeadLifecycleEvent(Base):
    __tablename__ = "crm_lead_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("lead_id", "sequence_number", name="uq_crm_lead_lifecycle_events_sequence"),
        UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_lead_lifecycle_events_source"),
        CheckConstraint("sequence_number > 0", name="ck_crm_lead_lifecycle_events_sequence"),
        CheckConstraint(
            "from_state IS NULL OR from_state IN ('DISCOVERED','ENRICHED','QUALIFIED','READY_FOR_REVIEW','ARCHIVED')",
            name="ck_crm_lead_lifecycle_events_from_state",
        ),
        CheckConstraint(
            "to_state IN ('DISCOVERED','ENRICHED','QUALIFIED','READY_FOR_REVIEW','ARCHIVED')",
            name="ck_crm_lead_lifecycle_events_to_state",
        ),
        CheckConstraint(
            "(from_state IS NULL AND to_state='DISCOVERED') OR from_state IS NOT NULL",
            name="ck_crm_lead_lifecycle_events_initialization",
        ),
        CheckConstraint(
            "length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100",
            name="ck_crm_lead_lifecycle_events_namespace",
        ),
        CheckConstraint(
            "length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512",
            name="ck_crm_lead_lifecycle_events_source_key",
        ),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_lead_lifecycle_events_fingerprint"),
        Index("ix_crm_lead_lifecycle_events_lead_time", "lead_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    lead = relationship("Lead")
