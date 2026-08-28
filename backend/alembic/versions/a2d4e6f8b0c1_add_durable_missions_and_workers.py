"""add durable missions and workers

Revision ID: a2d4e6f8b0c1
Revises: 7792cc7a4e20
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "a2d4e6f8b0c1"
down_revision = "7792cc7a4e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("workflow_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_data", sa.Text(), nullable=True),
        sa.Column("required_capability", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("current_worker_name", sa.String(), nullable=True),
        sa.Column("result_data", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_missions_idempotency_key"),
    )
    op.create_index("ix_missions_status", "missions", ["status"])
    op.create_index("ix_missions_workflow_name", "missions", ["workflow_name"])
    op.create_index(
        "ix_missions_current_worker_name",
        "missions",
        ["current_worker_name"],
    )

    op.create_table(
        "workers",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("worker_type", sa.String(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_mission_id", sa.String(), nullable=True),
        sa.Column("missions_completed", sa.Integer(), nullable=False),
        sa.Column("missions_failed", sa.Integer(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index("ix_workers_status", "workers", ["status"])
    op.create_index(
        "ix_workers_current_mission_id",
        "workers",
        ["current_mission_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workers_current_mission_id", table_name="workers")
    op.drop_index("ix_workers_status", table_name="workers")
    op.drop_table("workers")
    op.drop_index("ix_missions_current_worker_name", table_name="missions")
    op.drop_index("ix_missions_workflow_name", table_name="missions")
    op.drop_index("ix_missions_status", table_name="missions")
    op.drop_table("missions")
