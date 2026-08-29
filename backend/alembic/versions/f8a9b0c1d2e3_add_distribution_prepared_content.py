"""add durable prepared distribution content snapshot"""

from alembic import op
import sqlalchemy as sa


revision = "f8a9b0c1d2e3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable preserves any pre-correction development rows without inventing
    # content. New DistributionRun creation always persists a canonical body.
    op.add_column("distribution_runs", sa.Column("prepared_content_body", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("distribution_runs", "prepared_content_body")
