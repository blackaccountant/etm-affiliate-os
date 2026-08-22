"""merge content versioning and retry persistence heads

Revision ID: af7abf00e505
Revises: 5f990d3273c8, ee105ddd975f
Create Date: 2026-08-17 13:41:02.443381

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af7abf00e505'
down_revision: Union[str, Sequence[str], None] = ('5f990d3273c8', 'ee105ddd975f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
