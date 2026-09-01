"""advance stale mutable cold-delivery event cursors without rewinding history

Revision ID: f2e3d4c5b6a7
Revises: e1f2a3b4c5d6
"""

from alembic import op


revision = "f2e3d4c5b6a7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    # Events are immutable: only advance a stale mutable cursor.  Deployment
    # must quiesce cold workers so an old writer cannot recreate stale state.
    op.execute("""
        WITH max_events AS (
            SELECT operation_id, MAX(sequence_number) AS max_sequence
            FROM cold_delivery_events
            GROUP BY operation_id
        )
        UPDATE cold_delivery_operation_state AS state
        SET next_event_sequence = GREATEST(state.next_event_sequence, max_events.max_sequence + 1)
        FROM max_events
        WHERE state.operation_id = max_events.operation_id
          AND state.next_event_sequence <= max_events.max_sequence
    """)


def downgrade():
    # Never move repaired cursors backward: data repair is deliberately retained.
    pass
