"""add immutable outreach intent and message

Revision ID: a0b1c2d3e4f5
Revises: f0a1b2c3d4e5
"""

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_intents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("contact_point_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("purpose_key", sa.String(128), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("eligibility_policy_version", sa.String(128), nullable=False),
        sa.Column("creation_contactability_state", sa.String(32), nullable=False),
        sa.Column("contactability_evaluated_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contactability_decision_fingerprint", sa.String(64), nullable=False),
        sa.Column("contactability_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('EMAIL','SMS','WHATSAPP','TELEGRAM')", name="ck_outreach_intents_channel"),
        sa.CheckConstraint("length(trim(purpose_key)) > 0 AND length(purpose_key) <= 128", name="ck_outreach_intents_purpose"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_intents_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_intents_source_key"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_outreach_intents_request_fingerprint"),
        sa.CheckConstraint("length(contactability_decision_fingerprint) = 64", name="ck_outreach_intents_decision_fingerprint"),
        sa.CheckConstraint("creation_contactability_state = 'CONTACTABLE'", name="ck_outreach_intents_creation_contactable"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
        sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_intents_source"),
    )
    op.create_index("ix_outreach_intents_lead_created", "outreach_intents", ["lead_id", "created_at"])
    op.create_index("ix_outreach_intents_contact_point", "outreach_intents", ["contact_point_id"])
    op.create_table(
        "outreach_messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("outreach_intent_id", sa.String(36), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(16), nullable=False),
        sa.Column("channel_metadata", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(body)) > 0", name="ck_outreach_messages_body"),
        sa.CheckConstraint("content_format IN ('TEXT','HTML')", name="ck_outreach_messages_format"),
        sa.CheckConstraint("length(content_fingerprint) = 64", name="ck_outreach_messages_fingerprint"),
        sa.ForeignKeyConstraint(["outreach_intent_id"], ["outreach_intents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outreach_intent_id", name="uq_outreach_messages_intent"),
    )


def downgrade() -> None:
    op.drop_table("outreach_messages")
    op.drop_index("ix_outreach_intents_contact_point", table_name="outreach_intents")
    op.drop_index("ix_outreach_intents_lead_created", table_name="outreach_intents")
    op.drop_table("outreach_intents")
