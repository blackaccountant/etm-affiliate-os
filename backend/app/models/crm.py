"""Additive durable models for the M8A CRM persistence foundation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Lead(Base):
    __tablename__ = "crm_leads"
    __table_args__ = (
        UniqueConstraint("subject_id", name="uq_crm_leads_subject_id"),
        Index("ix_crm_leads_subject_id", "subject_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("audience_subjects.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    subject = relationship("AudienceSubject")
    contact_points = relationship("ContactPoint", back_populates="lead")


class ContactPoint(Base):
    __tablename__ = "crm_contact_points"
    __table_args__ = (
        UniqueConstraint("kind", "normalized_value", name="uq_crm_contact_points_identity"),
        UniqueConstraint("id", "lead_id", name="uq_crm_contact_points_id_lead"),
        CheckConstraint("kind IN ('EMAIL','PHONE','TELEGRAM','WEBSITE','SOCIAL_PROFILE')", name="ck_crm_contact_points_kind"),
        CheckConstraint("length(trim(normalized_value)) > 0", name="ck_crm_contact_points_normalized_value"),
        Index("ix_crm_contact_points_lead_id", "lead_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    lead = relationship("Lead", back_populates="contact_points")


class ContactPointProvenance(Base):
    __tablename__ = "crm_contact_point_provenance"
    __table_args__ = (
        UniqueConstraint("contact_point_id", "provenance_fingerprint", name="uq_crm_contact_point_provenance_fingerprint"),
        UniqueConstraint("contact_point_id", "source_namespace", "source_event_id", name="uq_crm_contact_point_provenance_source_event"),
        CheckConstraint("source_type IN ('USER_PROVIDED','PUBLIC_BUSINESS_SOURCE','WEBSITE','FORM_SUBMISSION','IMPORT','AFFILIATE_SYSTEM','MANUAL')", name="ck_crm_contact_point_provenance_source_type"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_contact_point_provenance_namespace"),
        CheckConstraint("length(provenance_fingerprint) = 64", name="ck_crm_contact_point_provenance_fingerprint"),
        CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_contact_point_provenance_evidence_fingerprint"),
        Index("ix_crm_contact_point_provenance_contact", "contact_point_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    contact_point = relationship("ContactPoint")


class ContactPointStateEvent(Base):
    __tablename__ = "crm_contact_point_state_events"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_contact_point_state_events_source"),
        CheckConstraint("state IN ('ACTIVE','INVALID','RETIRED')", name="ck_crm_contact_point_state_events_state"),
        CheckConstraint("verification_state IN ('UNVERIFIED','VERIFIED')", name="ck_crm_contact_point_state_events_verification"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_contact_point_state_events_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_contact_point_state_events_source_key"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_contact_point_state_events_fingerprint"),
        Index("ix_crm_contact_point_state_events_contact_time", "contact_point_id", "occurred_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_point = relationship("ContactPoint")


class PermissionEvent(Base):
    __tablename__ = "crm_permission_events"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_permission_events_source"),
        CheckConstraint("channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_crm_permission_events_channel"),
        CheckConstraint("event_type IN ('UNKNOWN','CONSENTED','OPTED_OUT','REVOKED')", name="ck_crm_permission_events_type"),
        CheckConstraint("length(trim(purpose_key)) > 0 AND length(purpose_key) <= 128", name="ck_crm_permission_events_purpose"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_permission_events_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_permission_events_source_key"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_permission_events_fingerprint"),
        CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_permission_events_evidence_fingerprint"),
        Index("ix_crm_permission_events_contact_scope_time", "contact_point_id", "channel", "purpose_key", "occurred_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    jurisdiction_context: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_point = relationship("ContactPoint")


class SuppressionEvent(Base):
    __tablename__ = "crm_suppression_events"
    __table_args__ = (
        ForeignKeyConstraint(["contact_point_id", "lead_id"], ["crm_contact_points.id", "crm_contact_points.lead_id"], name="fk_crm_suppression_events_contact_owner"),
        UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_suppression_events_source"),
        CheckConstraint("scope IN ('GLOBAL_LEAD','LEAD_CHANNEL','CONTACT_POINT_CHANNEL')", name="ck_crm_suppression_events_scope"),
        CheckConstraint("channel IS NULL OR channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_crm_suppression_events_channel"),
        CheckConstraint("action IN ('APPLIED','LIFTED')", name="ck_crm_suppression_events_action"),
        CheckConstraint("reason IN ('OPT_OUT','BOUNCE','COMPLAINT','MANUAL','COMPLIANCE')", name="ck_crm_suppression_events_reason"),
        CheckConstraint("(scope='GLOBAL_LEAD' AND contact_point_id IS NULL AND channel IS NULL) OR (scope='LEAD_CHANNEL' AND contact_point_id IS NULL AND channel IS NOT NULL) OR (scope='CONTACT_POINT_CHANNEL' AND contact_point_id IS NOT NULL AND channel IS NOT NULL)", name="ck_crm_suppression_events_scope_fields"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_suppression_events_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_suppression_events_source_key"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_suppression_events_fingerprint"),
        CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_suppression_events_evidence_fingerprint"),
        Index("ix_crm_suppression_events_lead_scope_time", "lead_id", "scope", "effective_at"),
        Index("ix_crm_suppression_events_contact", "contact_point_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    contact_point_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lead = relationship("Lead")
    contact_point = relationship("ContactPoint", foreign_keys=[contact_point_id])
