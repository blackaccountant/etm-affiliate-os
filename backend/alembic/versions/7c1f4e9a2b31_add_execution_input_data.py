"""add durable execution input snapshot

Revision ID: 7c1f4e9a2b31
Revises: 92c34cf03698
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c1f4e9a2b31"
down_revision = "92c34cf03698"
branch_labels = None
depends_on = None


def upgrade():

    op.add_column(
        "executions",
        sa.Column(
            "input_data",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade():

    op.drop_column(
        "executions",
        "input_data",
    )