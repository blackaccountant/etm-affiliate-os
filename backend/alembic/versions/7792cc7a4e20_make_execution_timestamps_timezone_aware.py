"""make execution timestamps timezone aware

Revision ID: 7792cc7a4e20
Revises: 7c1f4e9a2b31
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7792cc7a4e20"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "7c1f4e9a2b31"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


EXECUTION_TIMESTAMP_COLUMNS = (
    "started_at",
    "completed_at",
    "next_retry_at",
)


def upgrade() -> None:
    """
    Convert execution timestamps from PostgreSQL
    TIMESTAMP WITHOUT TIME ZONE to TIMESTAMPTZ.

    Existing naive timestamps are interpreted as UTC.
    """

    # ==================================================
    # Migration-local timeout policy
    # ==================================================
    #
    # Disable statement timeout so PostgreSQL is allowed
    # to complete the type conversion.
    #
    # But do NOT wait indefinitely for a table lock.
    # If another application process holds an incompatible
    # lock for more than 10 seconds, fail explicitly.
    # ==================================================

    op.execute(
        "SET LOCAL statement_timeout = '0'"
    )

    op.execute(
        "SET LOCAL lock_timeout = '10s'"
    )


    # ==================================================
    # Timestamp conversion
    # ==================================================

    for column_name in EXECUTION_TIMESTAMP_COLUMNS:

        op.alter_column(
            "executions",
            column_name,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(
                timezone=True
            ),
            existing_nullable=True,
            postgresql_using=(
                f"{column_name} AT TIME ZONE 'UTC'"
            ),
        )


def downgrade() -> None:
    """
    Convert execution timestamps back to
    TIMESTAMP WITHOUT TIME ZONE.

    Values are converted to UTC before removing
    timezone information.
    """

    op.execute(
        "SET LOCAL statement_timeout = '0'"
    )

    op.execute(
        "SET LOCAL lock_timeout = '10s'"
    )


    for column_name in EXECUTION_TIMESTAMP_COLUMNS:

        op.alter_column(
            "executions",
            column_name,
            existing_type=sa.DateTime(
                timezone=True
            ),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using=(
                f"{column_name} AT TIME ZONE 'UTC'"
            ),
        )