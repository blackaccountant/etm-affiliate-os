"""
Add retry persistence fields to executions.

Revision ID: ee105ddd975f
Revises: eb78fc871a69
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# ---------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------

revision: str = "ee105ddd975f"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "eb78fc871a69"

branch_labels = None

depends_on = None


# ---------------------------------------------------------
# Upgrade
# ---------------------------------------------------------

def upgrade() -> None:
    """
    Add persistent retry information to executions.

    Existing execution records are preserved.
    Existing tables are not dropped or recreated.
    """

    op.add_column(
        "executions",
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=True,
            server_default="3",
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "next_retry_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "executions",
        sa.Column(
            "failure_type",
            sa.String(),
            nullable=True,
        ),
    )

    # Remove the temporary server default after existing
    # rows have been populated.
    op.alter_column(
        "executions",
        "max_retries",
        server_default=None,
    )


# ---------------------------------------------------------
# Downgrade
# ---------------------------------------------------------

def downgrade() -> None:
    """
    Remove persistent retry information.

    Only the fields introduced by this migration
    are removed.
    """

    op.drop_column(
        "executions",
        "failure_type",
    )

    op.drop_column(
        "executions",
        "next_retry_at",
    )

    op.drop_column(
        "executions",
        "max_retries",
    )