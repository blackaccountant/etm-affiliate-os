"""add immutable economic experiment observations

Revision ID: d7e8f9a0b1c2
Revises: c3d4e5f6a7b8
"""

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime


revision = "d7e8f9a0b1c2"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "economic_recommendation_experiment_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_reference", sa.String(255), nullable=False),
        sa.Column("activation_reference", sa.String(255), nullable=False),
        sa.Column("distribution_run_id", sa.String(36), sa.ForeignKey("distribution_runs.id"), nullable=False),
        sa.Column("actor_reference", sa.String(255), nullable=False),
        sa.Column("decision_reference", sa.String(255), nullable=False),
        sa.Column("authorized_at", UTCDateTime(), nullable=False),
        sa.Column("mission_id", sa.String(), sa.ForeignKey("missions.id"), nullable=False),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("executions.id"), nullable=False),
        *[sa.Column(name, sa.String(32), nullable=False) for name in ("mission_status", "execution_status", "distribution_run_status", "terminal_classification", "success_failure_classification")],
        sa.Column("external_post_id", sa.String(500), nullable=True), sa.Column("external_url", sa.String(1000), nullable=True),
        sa.Column("platform", sa.String(64), nullable=False), sa.Column("account_reference", sa.String(255), nullable=False), sa.Column("destination", sa.String(500), nullable=False),
        sa.Column("result_metadata", sa.JSON(), nullable=True), sa.Column("failure_category", sa.String(64), nullable=True), sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("distribution_run_completed_at", UTCDateTime(), nullable=True), sa.Column("execution_completed_at", UTCDateTime(), nullable=True), sa.Column("mission_completed_at", UTCDateTime(), nullable=True),
        sa.Column("execution_observation_policy_version", sa.String(128), nullable=False), sa.Column("execution_observation_contract_version", sa.String(128), nullable=False), sa.Column("execution_observation_semantics", sa.Text(), nullable=False),
        sa.Column("observation_fingerprint", sa.String(64), nullable=False), sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("observation_fingerprint", name="uq_economic_experiment_observations_fingerprint"),
    )
    op.create_index("ix_economic_experiment_observations_experiment", "economic_recommendation_experiment_observations", ["experiment_reference"])
    op.create_index("ix_economic_experiment_observations_distribution_run", "economic_recommendation_experiment_observations", ["distribution_run_id"])
    op.create_index("ix_economic_experiment_observations_execution", "economic_recommendation_experiment_observations", ["execution_id"])


def downgrade():
    op.drop_index("ix_economic_experiment_observations_execution", table_name="economic_recommendation_experiment_observations")
    op.drop_index("ix_economic_experiment_observations_distribution_run", table_name="economic_recommendation_experiment_observations")
    op.drop_index("ix_economic_experiment_observations_experiment", table_name="economic_recommendation_experiment_observations")
    op.drop_table("economic_recommendation_experiment_observations")
