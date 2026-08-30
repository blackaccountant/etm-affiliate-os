"""add audience intelligence foundation

Revision ID: a6b1c2d3e4f5
Revises: fa1b2c3d4e5f
"""

from alembic import op
import sqlalchemy as sa


revision = "a6b1c2d3e4f5"
down_revision = "fa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audience_research_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("scope_reference", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_audience_research_runs_idempotency_key"),
    )
    op.create_index("ix_audience_research_runs_scope_type", "audience_research_runs", ["scope_type"])
    op.create_index("ix_audience_research_runs_status", "audience_research_runs", ["status"])

    op.create_table(
        "audience_subjects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("subject_type IN ('PERSON', 'ORGANIZATION', 'ANONYMOUS')", name="ck_audience_subjects_type"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audience_subjects_subject_type", "audience_subjects", ["subject_type"])

    op.create_table(
        "audience_external_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("source_namespace", sa.String(length=100), nullable=False),
        sa.Column("identity_type", sa.String(length=64), nullable=False),
        sa.Column("normalized_reference", sa.String(length=512), nullable=False),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'FIRST_PARTY_VERIFIED')", name="ck_audience_external_identity_verification"),
        sa.ForeignKeyConstraint(["subject_id"], ["audience_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_namespace", "identity_type", "normalized_reference", name="uq_audience_external_identity_reference"),
    )
    op.create_index("ix_audience_external_identities_subject_id", "audience_external_identities", ["subject_id"])
    op.create_index("ix_audience_external_identities_namespace_type", "audience_external_identities", ["source_namespace", "identity_type"])

    op.create_table(
        "audience_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("research_run_id", sa.String(length=36), nullable=True),
        sa.Column("subject_id", sa.String(length=36), nullable=True),
        sa.Column("source_namespace", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("external_observation_id", sa.String(length=512), nullable=True),
        sa.Column("source_reference", sa.String(length=2000), nullable=True),
        sa.Column("observation_key", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_fact", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["research_run_id"], ["audience_research_runs.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["audience_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_key", name="uq_audience_observations_key"),
    )
    op.create_index("ix_audience_observations_research_run_id", "audience_observations", ["research_run_id"])
    op.create_index("ix_audience_observations_subject_id", "audience_observations", ["subject_id"])
    op.create_index("ix_audience_observations_source_namespace_type", "audience_observations", ["source_namespace", "source_type"])
    op.create_index("ix_audience_observations_observed_at", "audience_observations", ["observed_at"])
    op.create_index("ix_audience_observations_captured_at", "audience_observations", ["captured_at"])

    op.create_table(
        "audience_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("source_reference", sa.String(length=2000), nullable=False),
        sa.Column("source_uri", sa.String(length=2000), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("normalized_representation", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["observation_id"], ["audience_observations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", "evidence_fingerprint", name="uq_audience_evidence_observation_fingerprint"),
    )
    op.create_index("ix_audience_evidence_observation_id", "audience_evidence", ["observation_id"])
    op.create_index("ix_audience_evidence_captured_at", "audience_evidence", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_audience_evidence_captured_at", table_name="audience_evidence")
    op.drop_index("ix_audience_evidence_observation_id", table_name="audience_evidence")
    op.drop_table("audience_evidence")
    op.drop_index("ix_audience_observations_captured_at", table_name="audience_observations")
    op.drop_index("ix_audience_observations_observed_at", table_name="audience_observations")
    op.drop_index("ix_audience_observations_source_namespace_type", table_name="audience_observations")
    op.drop_index("ix_audience_observations_subject_id", table_name="audience_observations")
    op.drop_index("ix_audience_observations_research_run_id", table_name="audience_observations")
    op.drop_table("audience_observations")
    op.drop_index("ix_audience_external_identities_namespace_type", table_name="audience_external_identities")
    op.drop_index("ix_audience_external_identities_subject_id", table_name="audience_external_identities")
    op.drop_table("audience_external_identities")
    op.drop_index("ix_audience_subjects_subject_type", table_name="audience_subjects")
    op.drop_table("audience_subjects")
    op.drop_index("ix_audience_research_runs_status", table_name="audience_research_runs")
    op.drop_index("ix_audience_research_runs_scope_type", table_name="audience_research_runs")
    op.drop_table("audience_research_runs")
