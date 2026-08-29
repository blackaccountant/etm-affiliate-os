"""add generated content artifacts

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("generated_content_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("generation_run_id", sa.String(length=36), nullable=False),
        sa.Column("content_brief_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False), sa.Column("hook", sa.Text(), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("call_to_action", sa.Text(), nullable=False), sa.Column("affiliate_disclosure", sa.Text(), nullable=False), sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_run_id"], ["content_generation_runs.id"]), sa.ForeignKeyConstraint(["content_brief_id"], ["content_briefs.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("generation_run_id", name="uq_generated_content_artifacts_generation_run_id"))
    op.create_index("ix_generated_content_artifacts_generation_run_id", "generated_content_artifacts", ["generation_run_id"])
    op.create_index("ix_generated_content_artifacts_content_brief_id", "generated_content_artifacts", ["content_brief_id"])
    op.create_index("ix_generated_content_artifacts_status", "generated_content_artifacts", ["status"])
    op.create_index("ix_generated_content_artifacts_brief_status", "generated_content_artifacts", ["content_brief_id", "status"])
def downgrade(): op.drop_table("generated_content_artifacts")
