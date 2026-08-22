"""
Add mission fields to executions.

Revision ID: eb78fc871a69
Revises: 5ae0372b774f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# ---------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------

revision: str = "eb78fc871a69"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "5ae0372b774f"

branch_labels = None

depends_on = None


# ---------------------------------------------------------
# Upgrade
# ---------------------------------------------------------

def upgrade() -> None:
    """
    Add mission and execution tracking fields.

    This migration intentionally changes only the
    executions table.

    Existing products and product intelligence
    history are preserved.
    """

    op.add_column(
        "executions",
        sa.Column(
            "mission_id",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "mission_name",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "worker_name",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "result_data",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "completed_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "duration",
            sa.Float(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_executions_mission_id",
        "executions",
        ["mission_id"],
        unique=False,
    )


# ---------------------------------------------------------
# Downgrade
# ---------------------------------------------------------

def downgrade() -> None:
    """
    Remove the mission and execution tracking fields.

    This reverses only the changes made by upgrade().
    """

    op.drop_index(
        "ix_executions_mission_id",
        table_name="executions",
    )

    op.drop_column(
        "executions",
        "error",
    )

    op.drop_column(
        "executions",
        "retry_count",
    )

    op.drop_column(
        "executions",
        "duration",
    )

    op.drop_column(
        "executions",
        "completed_at",
    )

    op.drop_column(
        "executions",
        "started_at",
    )

    op.drop_column(
        "executions",
        "result_data",
    )

    op.drop_column(
        "executions",
        "worker_name",
    )

    op.drop_column(
        "executions",
        "mission_name",
    )

    op.drop_column(
        "executions",
        "mission_id",
    )