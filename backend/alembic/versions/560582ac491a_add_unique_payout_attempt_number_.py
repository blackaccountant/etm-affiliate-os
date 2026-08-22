"""add unique payout attempt number constraint

Revision ID: 560582ac491a
Revises: af7abf00e505
Create Date: 2026-08-20 22:06:54.355101

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "560582ac491a"
down_revision: Union[str, Sequence[str], None] = "af7abf00e505"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "uq_affiliate_payout_attempt_payout_attempt_number"
TABLE_NAME = "affiliate_payout_attempts"


def upgrade() -> None:
    """Add concurrency protection for payout attempt numbers."""

    op.create_unique_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        ["payout_id", "attempt_number"],
    )


def downgrade() -> None:
    """Remove concurrency protection for payout attempt numbers."""

    op.drop_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        type_="unique",
    )
