"""Add durable content brief ledger

Revision ID: a1b2c3d4e5f6
Revises: b3d1f9a6c2e4
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "b3d1f9a6c2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("discovery_run_id", sa.String(length=36), nullable=False),
        sa.Column("discovery_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("channel_intent", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("audience_intent", sa.Text(), nullable=True),
        sa.Column("audience_problem", sa.Text(), nullable=True),
        sa.Column("angle", sa.Text(), nullable=True),
        sa.Column("call_to_action", sa.Text(), nullable=True),
        sa.Column("tone", sa.String(length=64), nullable=True),
        sa.Column("required_disclosure", sa.Text(), nullable=True),
        sa.Column("key_benefits", sa.JSON(), nullable=True),
        sa.Column("proof_points", sa.JSON(), nullable=True),
        sa.Column("target_keywords", sa.JSON(), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["discovery_runs.id"]),
        sa.ForeignKeyConstraint(["discovery_candidate_id"], ["discovery_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_content_briefs_idempotency_key"),
    )
    op.create_index("ix_content_briefs_discovery_run_id", "content_briefs", ["discovery_run_id"])
    op.create_index("ix_content_briefs_discovery_candidate_id", "content_briefs", ["discovery_candidate_id"])
    op.create_index("ix_content_briefs_status", "content_briefs", ["status"])
    op.create_index("ix_content_briefs_idempotency_key", "content_briefs", ["idempotency_key"])
    op.create_index("ix_content_briefs_candidate_run", "content_briefs", ["discovery_run_id", "discovery_candidate_id"])

    op.create_table(
        "content_brief_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content_brief_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_observation_id", sa.String(length=36), nullable=False),
        sa.Column("usage_role", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_brief_id"], ["content_briefs.id"]),
        sa.ForeignKeyConstraint(["evidence_observation_id"], ["evidence_observations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_brief_id", "evidence_observation_id", "usage_role", name="uq_content_brief_evidence_tuple"),
    )
    op.create_index("ix_content_brief_evidence_content_brief_id", "content_brief_evidence", ["content_brief_id"])
    op.create_index("ix_content_brief_evidence_evidence_observation_id", "content_brief_evidence", ["evidence_observation_id"])
    op.create_index("ix_content_brief_evidence_brief_usage", "content_brief_evidence", ["content_brief_id", "usage_role"])

    op.create_table(
        "content_generation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content_brief_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("generation_parameters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_brief_id"], ["content_briefs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_content_generation_runs_idempotency_key"),
    )
    op.create_index("ix_content_generation_runs_content_brief_id", "content_generation_runs", ["content_brief_id"])
    op.create_index("ix_content_generation_runs_status", "content_generation_runs", ["status"])
    op.create_index("ix_content_generation_runs_idempotency_key", "content_generation_runs", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_content_generation_runs_idempotency_key", table_name="content_generation_runs")
    op.drop_index("ix_content_generation_runs_status", table_name="content_generation_runs")
    op.drop_index("ix_content_generation_runs_content_brief_id", table_name="content_generation_runs")
    op.drop_table("content_generation_runs")
    op.drop_index("ix_content_brief_evidence_brief_usage", table_name="content_brief_evidence")
    op.drop_index("ix_content_brief_evidence_evidence_observation_id", table_name="content_brief_evidence")
    op.drop_index("ix_content_brief_evidence_content_brief_id", table_name="content_brief_evidence")
    op.drop_table("content_brief_evidence")
    op.drop_index("ix_content_briefs_candidate_run", table_name="content_briefs")
    op.drop_index("ix_content_briefs_idempotency_key", table_name="content_briefs")
    op.drop_index("ix_content_briefs_status", table_name="content_briefs")
    op.drop_index("ix_content_briefs_discovery_candidate_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_discovery_run_id", table_name="content_briefs")
    op.drop_table("content_briefs")
