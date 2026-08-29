"""add content repurposing runs"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_repurposing_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_artifact_id", sa.String(36), sa.ForeignKey("generated_content_artifacts.id"), nullable=False),
        sa.Column("source_evaluation_id", sa.String(36), sa.ForeignKey("content_evaluations.id"), nullable=False),
        sa.Column("generation_run_id", sa.String(36), sa.ForeignKey("content_generation_runs.id"), nullable=False, unique=True),
        sa.Column("result_artifact_id", sa.String(36), sa.ForeignKey("generated_content_artifacts.id"), nullable=True, unique=True),
        sa.Column("target_content_type", sa.String(64), nullable=False),
        sa.Column("channel_intent", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_content_repurposing_runs_source_artifact_id", ["source_artifact_id"]),
        ("ix_content_repurposing_runs_source_evaluation_id", ["source_evaluation_id"]),
        ("ix_content_repurposing_runs_status", ["status"]),
        ("ix_content_repurposing_runs_target_content_type", ["target_content_type"]),
    ):
        op.create_index(name, "content_repurposing_runs", columns)


def downgrade():
    op.drop_table("content_repurposing_runs")
