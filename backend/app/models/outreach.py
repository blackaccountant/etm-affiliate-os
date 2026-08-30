"""Immutable M9A outreach intent and prepared message models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class OutreachIntent(Base):
    __tablename__ = "outreach_intents"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_intents_source"),
        CheckConstraint("channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_outreach_intents_channel"),
        CheckConstraint("length(trim(purpose_key)) > 0 AND length(purpose_key) <= 128", name="ck_outreach_intents_purpose"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_intents_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_intents_source_key"),
        CheckConstraint("length(request_fingerprint) = 64", name="ck_outreach_intents_request_fingerprint"),
        CheckConstraint("length(contactability_decision_fingerprint) = 64", name="ck_outreach_intents_decision_fingerprint"),
        CheckConstraint("creation_contactability_state = 'CONTACTABLE'", name="ck_outreach_intents_creation_contactable"),
        Index("ix_outreach_intents_lead_created", "lead_id", "created_at"),
        Index("ix_outreach_intents_contact_point", "contact_point_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    eligibility_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    creation_contactability_state: Mapped[str] = mapped_column(String(32), nullable=False)
    contactability_evaluated_as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    contactability_decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    contactability_evidence: Mapped[object] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    message = relationship("OutreachMessage", back_populates="intent", uselist=False)


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    __table_args__ = (
        UniqueConstraint("outreach_intent_id", name="uq_outreach_messages_intent"),
        CheckConstraint("length(trim(body)) > 0", name="ck_outreach_messages_body"),
        CheckConstraint("content_format IN ('TEXT','HTML')", name="ck_outreach_messages_format"),
        CheckConstraint("length(content_fingerprint) = 64", name="ck_outreach_messages_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    outreach_intent_id: Mapped[str] = mapped_column(ForeignKey("outreach_intents.id"), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_metadata: Mapped[object] = mapped_column(JSON, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    intent = relationship("OutreachIntent", back_populates="message")
