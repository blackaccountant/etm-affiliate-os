"""M9C2B immutable cold-delivery facts and one mutable operation control row."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ColdDeliveryOperation(Base):
    __tablename__ = "cold_delivery_operations"
    __table_args__ = (
        ForeignKeyConstraint(["cold_authorization_id", "lead_id", "contact_point_id"], ["cold_prospecting_authorizations.id", "cold_prospecting_authorizations.lead_id", "cold_prospecting_authorizations.contact_point_id"], name="fk_cold_delivery_operations_authorization_owner"),
        UniqueConstraint("cold_authorization_id", name="uq_cold_delivery_operations_authorization"),
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_delivery_operations_source"),
        UniqueConstraint("id", "message_content_fingerprint", name="uq_cold_delivery_operations_message"),
        CheckConstraint("action IN ('INITIAL','FOLLOW_UP')", name="ck_cold_delivery_operations_action"),
        CheckConstraint("purpose_key LIKE 'cold_b2b:%'", name="ck_cold_delivery_operations_purpose"),
        CheckConstraint("length(message_content_fingerprint) = 64", name="ck_cold_delivery_operations_message_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cold_authorization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lead_id: Mapped[str] = mapped_column(ForeignKey("crm_leads.id"), nullable=False)
    contact_point_id: Mapped[str] = mapped_column(ForeignKey("crm_contact_points.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose_key: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose_family: Mapped[str] = mapped_column(String(128), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    message_content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdMessageContent(Base):
    __tablename__ = "cold_message_contents"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_cold_message_contents_operation"),
        ForeignKeyConstraint(["operation_id", "content_fingerprint"], ["cold_delivery_operations.id", "cold_delivery_operations.message_content_fingerprint"]),
        CheckConstraint("length(content_fingerprint) = 64", name="ck_cold_message_contents_fingerprint"),
        CheckConstraint("length(trim(body)) > 0", name="ck_cold_message_contents_body"),
        CheckConstraint("lower(coalesce(subject, '')) NOT LIKE '%@%' AND lower(body) NOT LIKE '%@%' AND lower(coalesce(subject, '')) NOT LIKE '%{{%' AND lower(body) NOT LIKE '%{{%' AND lower(coalesce(subject, '')) NOT LIKE '%${%' AND lower(body) NOT LIKE '%${%' AND lower(coalesce(subject, '')) NOT LIKE '%recipient%' AND lower(body) NOT LIKE '%recipient%' AND lower(coalesce(subject, '')) NOT LIKE '%destination%' AND lower(body) NOT LIKE '%destination%' AND lower(coalesce(subject, '')) NOT LIKE '%api_key%' AND lower(body) NOT LIKE '%api_key%' AND lower(coalesce(subject, '')) NOT LIKE '%provider_secret%' AND lower(body) NOT LIKE '%provider_secret%' AND lower(coalesce(subject, '')) NOT LIKE '%bearer%' AND lower(body) NOT LIKE '%bearer%' AND lower(coalesce(subject, '')) NOT LIKE '%password%' AND lower(body) NOT LIKE '%password%' AND lower(coalesce(subject, '')) NOT LIKE '%secret%' AND lower(body) NOT LIKE '%secret%'", name="ck_cold_message_contents_no_routing_or_secrets"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False)
    content_schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    @validates("subject", "body")
    def validate_content_text(self, key: str, value: str | None) -> str | None:
        from app.outreach.cold_delivery_contracts import validate_cold_message_text
        validate_cold_message_text(value if key == "subject" else self.subject, value if key == "body" else self.body)
        return value


class ColdDeliveryOperationState(Base):
    __tablename__ = "cold_delivery_operation_state"
    __table_args__ = (
        CheckConstraint("current_state IN ('CREATED','READY','T3_BLOCKED','DISPATCH_PLANNED','DISPATCHING','ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')", name="ck_cold_delivery_operation_state_value"),
        CheckConstraint("revision >= 1", name="ck_cold_delivery_operation_state_revision"),
        CheckConstraint("next_event_sequence >= 1", name="ck_cold_delivery_operation_state_sequence"),
    )
    operation_id: Mapped[str] = mapped_column(ForeignKey("cold_delivery_operations.id"), primary_key=True)
    current_state: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_fence_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_technical_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reconciliation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now)


class ColdDeliveryEvent(Base):
    __tablename__ = "cold_delivery_events"
    __table_args__ = (
        UniqueConstraint("operation_id", "sequence_number", name="uq_cold_delivery_events_operation_sequence"),
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_delivery_events_source"),
        CheckConstraint("sequence_number >= 1", name="ck_cold_delivery_events_sequence"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_cold_delivery_events_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(ForeignKey("cold_delivery_operations.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_payload: Mapped[object] = mapped_column(JSON, nullable=False)


class ColdT3Decision(Base):
    __tablename__ = "cold_t3_decisions"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_t3_decisions_source"),
        CheckConstraint("decision IN ('ALLOWED','BLOCKED')", name="ck_cold_t3_decisions_value"),
        CheckConstraint("length(authorization_fingerprint) = 64", name="ck_cold_t3_decisions_authorization_fingerprint"),
        CheckConstraint("length(policy_fingerprint) = 64", name="ck_cold_t3_decisions_policy_fingerprint"),
        CheckConstraint("length(authority_fingerprint) = 64", name="ck_cold_t3_decisions_authority_fingerprint"),
        CheckConstraint("length(recipient_fingerprint) = 64", name="ck_cold_t3_decisions_recipient_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(ForeignKey("cold_delivery_operations.id"), nullable=False)
    cold_authorization_id: Mapped[str] = mapped_column(ForeignKey("cold_prospecting_authorizations.id"), nullable=False)
    authorization_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    crm_evidence_ids: Mapped[object] = mapped_column(JSON, nullable=False)
    recipient_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[object] = mapped_column(JSON, nullable=False)
    decision_schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdProviderDispatch(Base):
    __tablename__ = "cold_provider_dispatches"
    __table_args__ = (
        UniqueConstraint("provider_key", "provider_operation_key", name="uq_cold_provider_dispatches_operation"),
        CheckConstraint("dispatch_status IN ('PLANNED','DISPATCHING','ACCEPTED','REJECTED','TECHNICAL_FAILURE')", name="ck_cold_provider_dispatches_status"),
        CheckConstraint("length(payload_fingerprint) = 64", name="ck_cold_provider_dispatches_payload_fingerprint"),
        CheckConstraint("length(sender_fingerprint) = 64", name="ck_cold_provider_dispatches_sender_fingerprint"),
        CheckConstraint("length(recipient_fingerprint) = 64", name="ck_cold_provider_dispatches_recipient_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(ForeignKey("cold_delivery_operations.id"), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    dispatch_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdProviderDispatchReference(Base):
    __tablename__ = "cold_provider_dispatch_references"
    __table_args__ = (
        UniqueConstraint("provider_dispatch_id", name="uq_cold_provider_dispatch_references_dispatch"),
        UniqueConstraint("provider_key", "provider_reference", name="uq_cold_provider_dispatch_references_value"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_dispatch_id: Mapped[str] = mapped_column(ForeignKey("cold_provider_dispatches.id"), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ColdProviderFeedbackReceipt(Base):
    __tablename__ = "cold_provider_feedback_receipts"
    __table_args__ = (
        UniqueConstraint("provider_key", "provider_event_key", name="uq_cold_provider_feedback_receipts_event"),
        CheckConstraint("length(event_fingerprint) = 64", name="ck_cold_provider_feedback_receipts_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_dispatch_id: Mapped[str] = mapped_column(ForeignKey("cold_provider_dispatches.id"), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    interpretation_version: Mapped[str] = mapped_column(String(128), nullable=False)
    interpretation_metadata: Mapped[object] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
