"""Immutable M9B delivery-attempt identity and append-only event history."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class OutreachDeliveryAttempt(Base):
    __tablename__ = "outreach_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_delivery_attempts_source"),
        UniqueConstraint("outreach_intent_id", "attempt_number", name="uq_outreach_delivery_attempts_intent_number"),
        CheckConstraint("attempt_number >= 1", name="ck_outreach_delivery_attempts_number"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_delivery_attempts_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_delivery_attempts_source_key"),
        CheckConstraint("length(request_fingerprint) = 64", name="ck_outreach_delivery_attempts_fingerprint"),
        Index("ix_outreach_delivery_attempts_intent", "outreach_intent_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    outreach_intent_id: Mapped[str] = mapped_column(ForeignKey("outreach_intents.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    intent = relationship("OutreachIntent")
    events = relationship("OutreachDeliveryEvent", back_populates="attempt")


class OutreachDeliveryEvent(Base):
    __tablename__ = "outreach_delivery_events"
    __table_args__ = (
        UniqueConstraint("delivery_attempt_id", "sequence_number", name="uq_outreach_delivery_events_attempt_sequence"),
        UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_delivery_events_source"),
        CheckConstraint("sequence_number >= 1", name="ck_outreach_delivery_events_sequence"),
        CheckConstraint("length(trim(event_type)) > 0 AND length(event_type) <= 64 AND event_type = upper(event_type)", name="ck_outreach_delivery_events_type"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_delivery_events_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_delivery_events_source_key"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_outreach_delivery_events_fingerprint"),
        Index("ix_outreach_delivery_events_attempt", "delivery_attempt_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    delivery_attempt_id: Mapped[str] = mapped_column(ForeignKey("outreach_delivery_attempts.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_payload: Mapped[object] = mapped_column(JSON, nullable=False)
    attempt = relationship("OutreachDeliveryAttempt", back_populates="events")
