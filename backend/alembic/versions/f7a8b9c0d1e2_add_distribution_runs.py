"""add durable distribution runs"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "distribution_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("generated_content_artifact_id", sa.String(36), sa.ForeignKey("generated_content_artifacts.id"), nullable=False),
        sa.Column("content_evaluation_id", sa.String(36), sa.ForeignKey("content_evaluations.id"), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("account_reference", sa.String(255), nullable=False),
        sa.Column("destination", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.String(500), nullable=True),
        sa.Column("external_url", sa.String(1000), nullable=True),
        sa.Column("result_metadata", sa.JSON, nullable=True),
        sa.Column("failure_category", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("publishing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_distribution_runs_idempotency_key"),
    )
    for name, columns in (
        ("ix_distribution_runs_generated_content_artifact_id", ["generated_content_artifact_id"]),
        ("ix_distribution_runs_content_evaluation_id", ["content_evaluation_id"]),
        ("ix_distribution_runs_status", ["status"]),
        ("ix_distribution_runs_scheduled_for", ["scheduled_for"]),
    ):
        op.create_index(name, "distribution_runs", columns)


def downgrade():
    op.drop_table("distribution_runs")
