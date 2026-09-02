"""add immutable global-cost allocation authority

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
"""

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime


revision = "c3d4e5f6a7b8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "affiliate_global_cost_allocation_batches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "affiliate_cost_event_id",
            sa.String(36),
            sa.ForeignKey("affiliate_cost_events.id"),
            nullable=False,
        ),
        sa.Column(
            "allocated_amount",
            sa.Numeric(18, 2),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("source_namespace", sa.String(63), nullable=False),
        sa.Column("source_event_digest", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "allocated_amount > 0",
            name="ck_affiliate_global_cost_allocation_batches_positive",
        ),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_affiliate_global_cost_allocation_batches_fingerprint",
        ),
        sa.CheckConstraint(
            "source_event_digest ~ '^[0-9a-f]{64}$'",
            name="ck_affiliate_global_cost_allocation_batches_source_digest",
        ),
        sa.CheckConstraint(
            "source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'",
            name="ck_affiliate_global_cost_allocation_batches_namespace",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "affiliate_cost_event_id",
            name="uq_affiliate_global_cost_allocation_batches_cost",
        ),
        sa.UniqueConstraint(
            "source_namespace",
            "source_event_digest",
            name="uq_affiliate_global_cost_allocation_batches_source",
        ),
    )

    op.create_table(
        "affiliate_global_cost_allocation_lines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "allocation_batch_id",
            sa.String(36),
            sa.ForeignKey(
                "affiliate_global_cost_allocation_batches.id"
            ),
            nullable=False,
        ),
        sa.Column(
            "affiliate_earning_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_earnings.id"),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(18, 2),
            nullable=False,
        ),
        sa.Column(
            "fingerprint",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            UTCDateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_affiliate_global_cost_allocation_lines_positive",
        ),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_affiliate_global_cost_allocation_lines_fingerprint",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "allocation_batch_id",
            "affiliate_earning_id",
            name="uq_affiliate_global_cost_allocation_lines_target",
        ),
    )

    op.create_index(
        "ix_affiliate_global_cost_allocation_lines_earning",
        "affiliate_global_cost_allocation_lines",
        ["affiliate_earning_id"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
        m10a9e_reject_global_cost_allocation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'M10A9E global cost allocations are immutable';
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_m10a9e_global_allocation_batch_immutable
        BEFORE UPDATE OR DELETE
        ON affiliate_global_cost_allocation_batches
        FOR EACH ROW
        EXECUTE FUNCTION
        m10a9e_reject_global_cost_allocation_mutation()
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_m10a9e_global_allocation_line_immutable
        BEFORE UPDATE OR DELETE
        ON affiliate_global_cost_allocation_lines
        FOR EACH ROW
        EXECUTE FUNCTION
        m10a9e_reject_global_cost_allocation_mutation()
        """
    )


def downgrade():
    op.execute(
        """
        DROP TRIGGER IF EXISTS
        trg_m10a9e_global_allocation_line_immutable
        ON affiliate_global_cost_allocation_lines
        """
    )

    op.execute(
        """
        DROP TRIGGER IF EXISTS
        trg_m10a9e_global_allocation_batch_immutable
        ON affiliate_global_cost_allocation_batches
        """
    )

    op.drop_index(
        "ix_affiliate_global_cost_allocation_lines_earning",
        table_name="affiliate_global_cost_allocation_lines",
    )

    op.drop_table(
        "affiliate_global_cost_allocation_lines"
    )
    op.drop_table(
        "affiliate_global_cost_allocation_batches"
    )

    op.execute(
        """
        DROP FUNCTION IF EXISTS
        m10a9e_reject_global_cost_allocation_mutation()
        """
    )
