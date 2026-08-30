"""add CRM contact permission persistence foundation

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""

from alembic import op
import sqlalchemy as sa


revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_leads",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["audience_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", name="uq_crm_leads_subject_id"),
    )
    op.create_index("ix_crm_leads_subject_id", "crm_leads", ["subject_id"])

    op.create_table(
        "crm_contact_points",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("normalized_value", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('EMAIL','PHONE','TELEGRAM','WEBSITE','SOCIAL_PROFILE')", name="ck_crm_contact_points_kind"),
        sa.CheckConstraint("length(trim(normalized_value)) > 0", name="ck_crm_contact_points_normalized_value"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "normalized_value", name="uq_crm_contact_points_identity"),
        sa.UniqueConstraint("id", "lead_id", name="uq_crm_contact_points_id_lead"),
    )
    op.create_index("ix_crm_contact_points_lead_id", "crm_contact_points", ["lead_id"])

    op.create_table(
        "crm_contact_point_provenance",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("contact_point_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_id", sa.String(512), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=True),
        sa.Column("provenance_fingerprint", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_type IN ('USER_PROVIDED','PUBLIC_BUSINESS_SOURCE','WEBSITE','FORM_SUBMISSION','IMPORT','AFFILIATE_SYSTEM','MANUAL')", name="ck_crm_contact_point_provenance_source_type"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_contact_point_provenance_namespace"),
        sa.CheckConstraint("length(provenance_fingerprint) = 64", name="ck_crm_contact_point_provenance_fingerprint"),
        sa.CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_contact_point_provenance_evidence_fingerprint"),
        sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_point_id", "provenance_fingerprint", name="uq_crm_contact_point_provenance_fingerprint"),
        sa.UniqueConstraint("contact_point_id", "source_namespace", "source_event_id", name="uq_crm_contact_point_provenance_source_event"),
    )
    op.create_index("ix_crm_contact_point_provenance_contact", "crm_contact_point_provenance", ["contact_point_id"])

    op.create_table(
        "crm_contact_point_state_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("contact_point_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("verification_state", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("state IN ('ACTIVE','INVALID','RETIRED')", name="ck_crm_contact_point_state_events_state"),
        sa.CheckConstraint("verification_state IN ('UNVERIFIED','VERIFIED')", name="ck_crm_contact_point_state_events_verification"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_contact_point_state_events_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_contact_point_state_events_source_key"),
        sa.CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_contact_point_state_events_fingerprint"),
        sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_contact_point_state_events_source"),
    )
    op.create_index("ix_crm_contact_point_state_events_contact_time", "crm_contact_point_state_events", ["contact_point_id", "occurred_at"])

    op.create_table(
        "crm_permission_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("contact_point_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("purpose_key", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("jurisdiction_context", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=True),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_crm_permission_events_channel"),
        sa.CheckConstraint("event_type IN ('UNKNOWN','CONSENTED','OPTED_OUT','REVOKED')", name="ck_crm_permission_events_type"),
        sa.CheckConstraint("length(trim(purpose_key)) > 0 AND length(purpose_key) <= 128", name="ck_crm_permission_events_purpose"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_permission_events_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_permission_events_source_key"),
        sa.CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_permission_events_fingerprint"),
        sa.CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_permission_events_evidence_fingerprint"),
        sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_permission_events_source"),
    )
    op.create_index("ix_crm_permission_events_contact_scope_time", "crm_permission_events", ["contact_point_id", "channel", "purpose_key", "occurred_at"])

    op.create_table(
        "crm_suppression_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("contact_point_id", sa.String(36), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=True),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("scope IN ('GLOBAL_LEAD','LEAD_CHANNEL','CONTACT_POINT_CHANNEL')", name="ck_crm_suppression_events_scope"),
        sa.CheckConstraint("channel IS NULL OR channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_crm_suppression_events_channel"),
        sa.CheckConstraint("action IN ('APPLIED','LIFTED')", name="ck_crm_suppression_events_action"),
        sa.CheckConstraint("reason IN ('OPT_OUT','BOUNCE','COMPLAINT','MANUAL','COMPLIANCE')", name="ck_crm_suppression_events_reason"),
        sa.CheckConstraint("(scope='GLOBAL_LEAD' AND contact_point_id IS NULL AND channel IS NULL) OR (scope='LEAD_CHANNEL' AND contact_point_id IS NULL AND channel IS NOT NULL) OR (scope='CONTACT_POINT_CHANNEL' AND contact_point_id IS NOT NULL AND channel IS NOT NULL)", name="ck_crm_suppression_events_scope_fields"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_crm_suppression_events_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_crm_suppression_events_source_key"),
        sa.CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_suppression_events_fingerprint"),
        sa.CheckConstraint("evidence_fingerprint IS NULL OR length(evidence_fingerprint) = 64", name="ck_crm_suppression_events_evidence_fingerprint"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
        sa.ForeignKeyConstraint(["contact_point_id", "lead_id"], ["crm_contact_points.id", "crm_contact_points.lead_id"], name="fk_crm_suppression_events_contact_owner"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_suppression_events_source"),
    )
    op.create_index("ix_crm_suppression_events_lead_scope_time", "crm_suppression_events", ["lead_id", "scope", "effective_at"])
    op.create_index("ix_crm_suppression_events_contact", "crm_suppression_events", ["contact_point_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_suppression_events_contact", table_name="crm_suppression_events")
    op.drop_index("ix_crm_suppression_events_lead_scope_time", table_name="crm_suppression_events")
    op.drop_table("crm_suppression_events")
    op.drop_index("ix_crm_permission_events_contact_scope_time", table_name="crm_permission_events")
    op.drop_table("crm_permission_events")
    op.drop_index("ix_crm_contact_point_state_events_contact_time", table_name="crm_contact_point_state_events")
    op.drop_table("crm_contact_point_state_events")
    op.drop_index("ix_crm_contact_point_provenance_contact", table_name="crm_contact_point_provenance")
    op.drop_table("crm_contact_point_provenance")
    op.drop_index("ix_crm_contact_points_lead_id", table_name="crm_contact_points")
    op.drop_table("crm_contact_points")
    op.drop_index("ix_crm_leads_subject_id", table_name="crm_leads")
    op.drop_table("crm_leads")
