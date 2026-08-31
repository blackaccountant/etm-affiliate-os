"""add immutable outreach provider dispatch and reference facts

Revision ID: c0d1e2f3a4b5
Revises: b0c1d2e3f4a5
"""

from alembic import op
import sqlalchemy as sa


revision = "c0d1e2f3a4b5"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_provider_dispatches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("delivery_attempt_id", sa.String(36), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("provider_contract_version", sa.String(128), nullable=False),
        sa.Column("provider_operation_key", sa.String(255), nullable=False),
        sa.Column("provider_operation_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider_payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("sender_identity_fingerprint", sa.String(64), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(provider_key)) > 0 AND length(provider_key) <= 64", name="ck_outreach_provider_dispatches_key"),
        sa.CheckConstraint("length(trim(provider_contract_version)) > 0 AND length(provider_contract_version) <= 128", name="ck_outreach_provider_dispatches_contract"),
        sa.CheckConstraint("length(trim(provider_operation_key)) > 0 AND length(provider_operation_key) <= 255", name="ck_outreach_provider_dispatches_operation_key"),
        sa.CheckConstraint("length(provider_operation_fingerprint) = 64", name="ck_outreach_provider_dispatches_operation_fingerprint"),
        sa.CheckConstraint("length(provider_payload_fingerprint) = 64", name="ck_outreach_provider_dispatches_payload_fingerprint"),
        sa.CheckConstraint("length(sender_identity_fingerprint) = 64", name="ck_outreach_provider_dispatches_sender_fingerprint"),
        sa.ForeignKeyConstraint(["delivery_attempt_id"], ["outreach_delivery_attempts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_attempt_id", name="uq_outreach_provider_dispatches_attempt"),
        sa.UniqueConstraint("provider_key", "provider_operation_key", name="uq_outreach_provider_dispatches_operation"),
    )
    op.create_index("ix_outreach_provider_dispatches_attempt", "outreach_provider_dispatches", ["delivery_attempt_id"])
    op.create_table(
        "outreach_provider_references",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_dispatch_id", sa.String(36), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(provider_key)) > 0 AND length(provider_key) <= 64", name="ck_outreach_provider_references_key"),
        sa.CheckConstraint("length(trim(provider_reference)) > 0 AND length(provider_reference) <= 255", name="ck_outreach_provider_references_value"),
        sa.ForeignKeyConstraint(["provider_dispatch_id"], ["outreach_provider_dispatches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_dispatch_id", name="uq_outreach_provider_references_dispatch"),
        sa.UniqueConstraint("provider_key", "provider_reference", name="uq_outreach_provider_references_value"),
    )
    op.create_index("ix_outreach_provider_references_lookup", "outreach_provider_references", ["provider_key", "provider_reference"])


def downgrade() -> None:
    op.drop_index("ix_outreach_provider_references_lookup", table_name="outreach_provider_references")
    op.drop_table("outreach_provider_references")
    op.drop_index("ix_outreach_provider_dispatches_attempt", table_name="outreach_provider_dispatches")
    op.drop_table("outreach_provider_dispatches")
