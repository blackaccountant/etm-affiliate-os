"""add CRM qualification links and lifecycle history

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""

from alembic import op
import sqlalchemy as sa


revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_lead_qualification_links",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
        sa.ForeignKeyConstraint(["assessment_id"], ["audience_qualification_assessments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "assessment_id", name="uq_crm_lead_qualification_links_identity"),
    )
    op.create_index(
        "ix_crm_lead_qualification_links_assessment",
        "crm_lead_qualification_links",
        ["assessment_id"],
    )

    op.create_table(
        "crm_lead_lifecycle_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_namespace", sa.String(100), nullable=False),
        sa.Column("source_event_key", sa.String(512), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("sequence_number > 0", name="ck_crm_lead_lifecycle_events_sequence"),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state IN ('DISCOVERED','ENRICHED','QUALIFIED','READY_FOR_REVIEW','ARCHIVED')",
            name="ck_crm_lead_lifecycle_events_from_state",
        ),
        sa.CheckConstraint(
            "to_state IN ('DISCOVERED','ENRICHED','QUALIFIED','READY_FOR_REVIEW','ARCHIVED')",
            name="ck_crm_lead_lifecycle_events_to_state",
        ),
        sa.CheckConstraint(
            "(from_state IS NULL AND to_state='DISCOVERED') OR from_state IS NOT NULL",
            name="ck_crm_lead_lifecycle_events_initialization",
        ),
        sa.CheckConstraint(
            "length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100",
            name="ck_crm_lead_lifecycle_events_namespace",
        ),
        sa.CheckConstraint(
            "length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512",
            name="ck_crm_lead_lifecycle_events_source_key",
        ),
        sa.CheckConstraint("length(event_fingerprint) = 64", name="ck_crm_lead_lifecycle_events_fingerprint"),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "sequence_number", name="uq_crm_lead_lifecycle_events_sequence"),
        sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_crm_lead_lifecycle_events_source"),
    )
    op.create_index(
        "ix_crm_lead_lifecycle_events_lead_time",
        "crm_lead_lifecycle_events",
        ["lead_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_lead_lifecycle_events_lead_time", table_name="crm_lead_lifecycle_events")
    op.drop_table("crm_lead_lifecycle_events")
    op.drop_index(
        "ix_crm_lead_qualification_links_assessment",
        table_name="crm_lead_qualification_links",
    )
    op.drop_table("crm_lead_qualification_links")
