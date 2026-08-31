"""Immutable provider-operation identity and opaque provider references."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class OutreachProviderDispatch(Base):
    __tablename__ = "outreach_provider_dispatches"
    __table_args__ = (
        UniqueConstraint("delivery_attempt_id", name="uq_outreach_provider_dispatches_attempt"),
        UniqueConstraint("provider_key", "provider_operation_key", name="uq_outreach_provider_dispatches_operation"),
        CheckConstraint("length(trim(provider_key)) > 0 AND length(provider_key) <= 64", name="ck_outreach_provider_dispatches_key"),
        CheckConstraint("length(trim(provider_contract_version)) > 0 AND length(provider_contract_version) <= 128", name="ck_outreach_provider_dispatches_contract"),
        CheckConstraint("length(trim(provider_operation_key)) > 0 AND length(provider_operation_key) <= 255", name="ck_outreach_provider_dispatches_operation_key"),
        CheckConstraint("length(provider_operation_fingerprint) = 64", name="ck_outreach_provider_dispatches_operation_fingerprint"),
        CheckConstraint("length(provider_payload_fingerprint) = 64", name="ck_outreach_provider_dispatches_payload_fingerprint"),
        CheckConstraint("length(sender_identity_fingerprint) = 64", name="ck_outreach_provider_dispatches_sender_fingerprint"),
        Index("ix_outreach_provider_dispatches_attempt", "delivery_attempt_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    delivery_attempt_id: Mapped[str] = mapped_column(ForeignKey("outreach_delivery_attempts.id"), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_operation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_identity_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    planned_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    dispatch_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    attempt = relationship("OutreachDeliveryAttempt")
    reference = relationship("OutreachProviderReference", back_populates="dispatch", uselist=False)


class OutreachProviderReference(Base):
    __tablename__ = "outreach_provider_references"
    __table_args__ = (
        UniqueConstraint("provider_dispatch_id", name="uq_outreach_provider_references_dispatch"),
        UniqueConstraint("provider_key", "provider_reference", name="uq_outreach_provider_references_value"),
        CheckConstraint("length(trim(provider_key)) > 0 AND length(provider_key) <= 64", name="ck_outreach_provider_references_key"),
        CheckConstraint("length(trim(provider_reference)) > 0 AND length(provider_reference) <= 255", name="ck_outreach_provider_references_value"),
        Index("ix_outreach_provider_references_lookup", "provider_key", "provider_reference"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_dispatch_id: Mapped[str] = mapped_column(ForeignKey("outreach_provider_dispatches.id"), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    dispatch = relationship("OutreachProviderDispatch", back_populates="reference")
