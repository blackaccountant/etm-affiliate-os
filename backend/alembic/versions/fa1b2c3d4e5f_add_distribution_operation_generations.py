"""add durable distribution operation generations"""

from alembic import op
import sqlalchemy as sa


revision = "fa1b2c3d4e5f"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("distribution_runs", sa.Column("publish_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("distribution_runs", sa.Column("reconciliation_generation", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("distribution_runs", "reconciliation_generation")
    op.drop_column("distribution_runs", "publish_generation")
