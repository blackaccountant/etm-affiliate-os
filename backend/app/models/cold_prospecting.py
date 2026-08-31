"""Immutable, provider-independent M9C2A cold B2B authorization records."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ColdProspectingOrganizationEvidence(Base):
    __tablename__ = "cold_prospecting_organization_evidence"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_org_evidence_source"),
        CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_cold_org_evidence_namespace"),
        CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_cold_org_evidence_source_key"),
        CheckConstraint("length(trim(evidence_reference)) > 0 AND length(evidence_reference) <= 512", name="ck_cold_org_evidence_reference"),
        CheckConstraint("length(evidence_fingerprint) = 64", name="ck_cold_org_evidence_fingerprint"),
        CheckConstraint("length(request_fingerprint) = 64", name="ck_cold_org_evidence_request_fingerprint"),
        Index("ix_cold_org_evidence_lead", "lead_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_reference: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_record_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acceptance_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_schema_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdProspectingAuthorization(Base):
    __tablename__ = "cold_prospecting_authorizations"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_authorizations_source"),
        CheckConstraint("channel = 'EMAIL'", name="ck_cold_authorizations_email"),
        CheckConstraint("purpose_key LIKE 'cold_b2b:%'", name="ck_cold_authorizations_purpose"),
        CheckConstraint("requested_action IN ('INITIAL','FOLLOW_UP')", name="ck_cold_authorizations_action"),
        CheckConstraint("authorization_state IN ('ELIGIBLE','INELIGIBLE','POLICY_UNAVAILABLE')", name="ck_cold_authorizations_state"),
        CheckConstraint("length(request_fingerprint) = 64", name="ck_cold_authorizations_request_fingerprint"),
        CheckConstraint("length(decision_fingerprint) = 64", name="ck_cold_authorizations_decision_fingerprint"),
        CheckConstraint("length(trim(policy_profile_key)) > 0 AND length(policy_profile_key) <= 128", name="ck_cold_authorizations_policy_key"),
        Index("ix_cold_authorizations_frequency", "lead_id", "contact_point_id", "channel", "purpose_family", "evaluated_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    organization_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("cold_prospecting_organization_evidence.id"), nullable=True)
    policy_selection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose_key: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose_family: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_action: Mapped[str] = mapped_column(String(32), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[object] = mapped_column(JSON, nullable=False)
    eligibility_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    frequency_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[object] = mapped_column(JSON, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdProspectingPolicySelection(Base):
    __tablename__ = "cold_prospecting_policy_selections"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_policy_selection_source"),
        UniqueConstraint("id", "lead_id", name="uq_cold_policy_selection_id_lead"),
        CheckConstraint("acceptance_state IN ('ACCEPTED','REJECTED')", name="ck_cold_policy_selection_acceptance"),
        CheckConstraint("length(evidence_fingerprint) = 64", name="ck_cold_policy_selection_evidence_fingerprint"),
        CheckConstraint("length(decision_fingerprint) = 64", name="ck_cold_policy_selection_decision_fingerprint"),
        Index("ix_cold_policy_selection_lead", "lead_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(128), nullable=False)
    acceptance_state: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
