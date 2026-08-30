"""add outreach delivery attempts and events

Revision ID: b0c1d2e3f4a5
Revises: a0b1c2d3e4f5
"""

from alembic import op
import sqlalchemy as sa


revision = "b0c1d2e3f4a5"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_delivery_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("outreach_intent_id", sa.String(36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_number >= 1", name="ck_outreach_delivery_attempts_number"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_delivery_attempts_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_delivery_attempts_source_key"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_outreach_delivery_attempts_fingerprint"),
        sa.ForeignKeyConstraint(["outreach_intent_id"], ["outreach_intents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_delivery_attempts_source"),
        sa.UniqueConstraint("outreach_intent_id", "attempt_number", name="uq_outreach_delivery_attempts_intent_number"),
    )
    op.create_index("ix_outreach_delivery_attempts_intent", "outreach_delivery_attempts", ["outreach_intent_id"])
    op.create_table(
        "outreach_delivery_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("delivery_attempt_id", sa.String(36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.Column("safe_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("sequence_number >= 1", name="ck_outreach_delivery_events_sequence"),
        sa.CheckConstraint("length(trim(event_type)) > 0 AND length(event_type) <= 64 AND event_type = upper(event_type)", name="ck_outreach_delivery_events_type"),
        sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_outreach_delivery_events_namespace"),
        sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_outreach_delivery_events_source_key"),
        sa.CheckConstraint("length(event_fingerprint) = 64", name="ck_outreach_delivery_events_fingerprint"),
        sa.ForeignKeyConstraint(["delivery_attempt_id"], ["outreach_delivery_attempts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_attempt_id", "sequence_number", name="uq_outreach_delivery_events_attempt_sequence"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_outreach_delivery_events_source"),
    )
    op.create_index("ix_outreach_delivery_events_attempt", "outreach_delivery_events", ["delivery_attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_delivery_events_attempt", table_name="outreach_delivery_events")
    op.drop_table("outreach_delivery_events")
    op.drop_index("ix_outreach_delivery_attempts_intent", table_name="outreach_delivery_attempts")
    op.drop_table("outreach_delivery_attempts")
