"""add durable discovery ledger

Revision ID: b3d1f9a6c2e4
Revises: a2d4e6f8b0c1
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "b3d1f9a6c2e4"
down_revision = "a2d4e6f8b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("input_type", sa.String(length=32), nullable=False),
        sa.Column("input_value", sa.Text(), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("verified_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_discovery_runs_idempotency_key"),
    )
    op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])
    op.create_index("ix_discovery_runs_input_type", "discovery_runs", ["input_type"])
    op.create_index("ix_discovery_runs_idempotency_key", "discovery_runs", ["idempotency_key"])

    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_adapter", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("vendor_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_domain", sa.String(length=255), nullable=False),
        sa.Column("offer_name", sa.String(length=255), nullable=True),
        sa.Column("program_name", sa.String(length=255), nullable=True),
        sa.Column("affiliate_network", sa.String(length=255), nullable=True),
        sa.Column("affiliate_url", sa.String(length=2000), nullable=True),
        sa.Column("program_identity_key", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=100), nullable=False),
        sa.Column("commission_model", sa.String(length=32), nullable=False),
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("commission_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("commission_currency", sa.String(length=3), nullable=True),
        sa.Column("recurring_period", sa.String(length=100), nullable=True),
        sa.Column("cookie_days", sa.Integer(), nullable=True),
        sa.Column("payout_threshold", sa.Numeric(14, 2), nullable=True),
        sa.Column("payout_currency", sa.String(length=3), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("score_breakdown", sa.JSON(), nullable=True),
        sa.Column("score_reasons", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("commission_percent IS NULL OR (commission_percent >= 0 AND commission_percent <= 100)", name="ck_discovery_candidate_commission_percent"),
        sa.CheckConstraint("cookie_days IS NULL OR cookie_days >= 0", name="ck_discovery_candidate_cookie_days"),
        sa.CheckConstraint("payout_threshold IS NULL OR payout_threshold >= 0", name="ck_discovery_candidate_payout_threshold"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 100)", name="ck_discovery_candidate_confidence"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_discovery_candidate_score"),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "dedupe_key", name="uq_discovery_candidates_run_dedupe"),
    )
    op.create_index("ix_discovery_candidates_run_id", "discovery_candidates", ["run_id"])
    op.create_index("ix_discovery_candidates_canonical_domain", "discovery_candidates", ["canonical_domain"])
    op.create_index("ix_discovery_candidates_program_identity_key", "discovery_candidates", ["program_identity_key"])

    op.create_table(
        "evidence_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("claim_type", sa.String(length=100), nullable=False),
        sa.Column("observed_value", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("extractor", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["discovery_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_observations_candidate_id", "evidence_observations", ["candidate_id"])
    op.create_index("ix_evidence_observations_candidate_claim", "evidence_observations", ["candidate_id", "claim_type"])


def downgrade() -> None:
    op.drop_index("ix_evidence_observations_candidate_claim", table_name="evidence_observations")
    op.drop_index("ix_evidence_observations_candidate_id", table_name="evidence_observations")
    op.drop_table("evidence_observations")
    op.drop_index("ix_discovery_candidates_program_identity_key", table_name="discovery_candidates")
    op.drop_index("ix_discovery_candidates_canonical_domain", table_name="discovery_candidates")
    op.drop_index("ix_discovery_candidates_run_id", table_name="discovery_candidates")
    op.drop_table("discovery_candidates")
    op.drop_index("ix_discovery_runs_idempotency_key", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_input_type", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_status", table_name="discovery_runs")
    op.drop_table("discovery_runs")
