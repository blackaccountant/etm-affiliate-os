"""harden production schema alignment

Revision ID: 9f3c2a7d6b41
Revises: c3d4e5f6a7b8
"""

from alembic import op
import sqlalchemy as sa


_PUBLISHING_QUEUE_UQ_NAME = (
    "uq_publishing_queue_asset_channel"
)

_PUBLISHING_QUEUE_UQ_COLUMNS = (
    "content_asset_id",
    "channel",
)

_PUBLISHING_QUEUE_UQ_MARKER = (
    "PR1B2:9f3c2a7d6b41"
)


def _publishing_queue_uq_columns(bind):
    inspector = sa.inspect(bind)

    matches = [
        tuple(
            constraint.get("column_names")
            or ()
        )
        for constraint
        in inspector.get_unique_constraints(
            "publishing_queue",
            schema="public",
        )
        if constraint.get("name")
        == _PUBLISHING_QUEUE_UQ_NAME
    ]

    if len(matches) > 1:
        raise RuntimeError(
            "Multiple publishing_queue unique "
            "constraints found with the PR1B2 "
            "authority name."
        )

    if not matches:
        return None

    return matches[0]


def _publishing_queue_uq_comment(bind):
    return bind.execute(
        sa.text(
            """
            SELECT obj_description(
                constraint_row.oid,
                'pg_constraint'
            )
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid =
                 constraint_row.conrelid
            JOIN pg_namespace AS namespace_row
              ON namespace_row.oid =
                 table_row.relnamespace
            WHERE namespace_row.nspname = 'public'
              AND table_row.relname =
                  'publishing_queue'
              AND constraint_row.conname =
                  :constraint_name
            """
        ),
        {
            "constraint_name":
                _PUBLISHING_QUEUE_UQ_NAME,
        },
    ).scalar_one_or_none()


def _ensure_publishing_queue_asset_channel_unique():
    bind = op.get_bind()

    columns = _publishing_queue_uq_columns(
        bind
    )

    if columns is None:
        op.create_unique_constraint(
            _PUBLISHING_QUEUE_UQ_NAME,
            "publishing_queue",
            list(
                _PUBLISHING_QUEUE_UQ_COLUMNS
            ),
        )

        bind.execute(
            sa.text(
                """
                COMMENT ON CONSTRAINT
                uq_publishing_queue_asset_channel
                ON public.publishing_queue
                IS 'PR1B2:9f3c2a7d6b41'
                """
            )
        )

        return

    if columns != _PUBLISHING_QUEUE_UQ_COLUMNS:
        raise RuntimeError(
            "Existing publishing_queue authority "
            "constraint has unexpected columns: "
            f"{columns!r}"
        )


def _revert_publishing_queue_asset_channel_unique():
    bind = op.get_bind()

    columns = _publishing_queue_uq_columns(
        bind
    )

    if columns is None:
        return

    if columns != _PUBLISHING_QUEUE_UQ_COLUMNS:
        raise RuntimeError(
            "Publishing_queue authority constraint "
            "changed unexpectedly before downgrade: "
            f"{columns!r}"
        )

    marker = _publishing_queue_uq_comment(
        bind
    )

    # Preserve any constraint that existed before
    # PR1B2. Only remove the fresh-chain repair
    # created and tagged by this migration.
    if marker == _PUBLISHING_QUEUE_UQ_MARKER:
        op.drop_constraint(
            _PUBLISHING_QUEUE_UQ_NAME,
            "publishing_queue",
            type_="unique",
        )


revision = "9f3c2a7d6b41"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    _ensure_publishing_queue_asset_channel_unique()

    # ---------------------------------------------------------
    # affiliate_content_assets
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_content_assets_product_id",
        "affiliate_content_assets",
        ["product_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # affiliate_conversions
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_conversions_affiliate_link_id",
        "affiliate_conversions",
        ["affiliate_link_id"],
        unique=False,
    )
    op.create_index(
        "ix_affiliate_conversions_affiliate_program_id",
        "affiliate_conversions",
        ["affiliate_program_id"],
        unique=False,
    )
    op.create_index(
        "ix_affiliate_conversions_external_conversion_id",
        "affiliate_conversions",
        ["external_conversion_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_affiliate_conversion_external_id",
        "affiliate_conversions",
        ["affiliate_program_id", "external_conversion_id"],
    )

    op.drop_constraint(
        "affiliate_conversions_affiliate_link_id_fkey",
        "affiliate_conversions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "affiliate_conversions_affiliate_program_id_fkey",
        "affiliate_conversions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "affiliate_conversions_affiliate_link_id_fkey",
        "affiliate_conversions",
        "affiliate_links",
        ["affiliate_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "affiliate_conversions_affiliate_program_id_fkey",
        "affiliate_conversions",
        "affiliate_programs",
        ["affiliate_program_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------
    # affiliate_earnings
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_earnings_affiliate_program_id",
        "affiliate_earnings",
        ["affiliate_program_id"],
        unique=False,
    )
    op.create_index(
        "ix_affiliate_earnings_conversion_id",
        "affiliate_earnings",
        ["conversion_id"],
        unique=False,
    )
    op.create_index(
        "ix_affiliate_earnings_payout_id",
        "affiliate_earnings",
        ["payout_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_affiliate_earning_conversion_id",
        "affiliate_earnings",
        ["conversion_id"],
    )

    op.drop_constraint(
        "affiliate_earnings_affiliate_program_id_fkey",
        "affiliate_earnings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "affiliate_earnings_conversion_id_fkey",
        "affiliate_earnings",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "affiliate_earnings_affiliate_program_id_fkey",
        "affiliate_earnings",
        "affiliate_programs",
        ["affiliate_program_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "affiliate_earnings_payout_id_fkey",
        "affiliate_earnings",
        "affiliate_payouts",
        ["payout_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "affiliate_earnings_conversion_id_fkey",
        "affiliate_earnings",
        "affiliate_conversions",
        ["conversion_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------
    # affiliate_links
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_links_tracking_code",
        "affiliate_links",
        ["tracking_code"],
        unique=True,
    )
    op.create_foreign_key(
        "affiliate_links_content_asset_id_fkey",
        "affiliate_links",
        "affiliate_content_assets",
        ["content_asset_id"],
        ["id"],
    )

    # ---------------------------------------------------------
    # affiliate_opportunities
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_opportunities_product_id",
        "affiliate_opportunities",
        ["product_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # affiliate_payout_attempts
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_payout_attempts_payout_id",
        "affiliate_payout_attempts",
        ["payout_id"],
        unique=False,
    )
    op.create_index(
        "ix_affiliate_payout_attempts_status",
        "affiliate_payout_attempts",
        ["status"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_affiliate_payout_attempts_idempotency_key",
        "affiliate_payout_attempts",
        ["idempotency_key"],
    )

    op.drop_constraint(
        "affiliate_payout_attempts_payout_id_fkey",
        "affiliate_payout_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "affiliate_payout_attempts_payout_id_fkey",
        "affiliate_payout_attempts",
        "affiliate_payouts",
        ["payout_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ---------------------------------------------------------
    # affiliate_payouts
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_payouts_affiliate_program_id",
        "affiliate_payouts",
        ["affiliate_program_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # affiliate_programs
    # ---------------------------------------------------------
    op.create_index(
        "ix_affiliate_programs_product_id",
        "affiliate_programs",
        ["product_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # content_approvals
    # ---------------------------------------------------------
    op.create_index(
        "ix_content_approvals_content_asset_id",
        "content_approvals",
        ["content_asset_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # content_brief_evidence
    # ---------------------------------------------------------
    op.create_index(
        "ix_content_brief_evidence_usage_role",
        "content_brief_evidence",
        ["usage_role"],
        unique=False,
    )

    # ---------------------------------------------------------
    # content_seo_scores
    # ---------------------------------------------------------
    op.create_index(
        "ix_content_seo_scores_content_asset_id",
        "content_seo_scores",
        ["content_asset_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # product_intelligence_history
    # ---------------------------------------------------------
    op.create_index(
        "ix_product_intelligence_history_product_id",
        "product_intelligence_history",
        ["product_id"],
        unique=False,
    )


def downgrade():
    # ---------------------------------------------------------
    # product_intelligence_history
    # ---------------------------------------------------------
    op.drop_index(
        "ix_product_intelligence_history_product_id",
        table_name="product_intelligence_history",
    )

    # ---------------------------------------------------------
    # content_seo_scores
    # ---------------------------------------------------------
    op.drop_index(
        "ix_content_seo_scores_content_asset_id",
        table_name="content_seo_scores",
    )

    # ---------------------------------------------------------
    # content_brief_evidence
    # ---------------------------------------------------------
    op.drop_index(
        "ix_content_brief_evidence_usage_role",
        table_name="content_brief_evidence",
    )

    # ---------------------------------------------------------
    # content_approvals
    # ---------------------------------------------------------
    op.drop_index(
        "ix_content_approvals_content_asset_id",
        table_name="content_approvals",
    )

    # ---------------------------------------------------------
    # affiliate_programs
    # ---------------------------------------------------------
    op.drop_index(
        "ix_affiliate_programs_product_id",
        table_name="affiliate_programs",
    )

    # ---------------------------------------------------------
    # affiliate_payouts
    # ---------------------------------------------------------
    op.drop_index(
        "ix_affiliate_payouts_affiliate_program_id",
        table_name="affiliate_payouts",
    )

    # ---------------------------------------------------------
    # affiliate_payout_attempts
    # ---------------------------------------------------------
    op.drop_constraint(
        "affiliate_payout_attempts_payout_id_fkey",
        "affiliate_payout_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "affiliate_payout_attempts_payout_id_fkey",
        "affiliate_payout_attempts",
        "affiliate_payouts",
        ["payout_id"],
        ["id"],
    )

    op.drop_constraint(
        "uq_affiliate_payout_attempts_idempotency_key",
        "affiliate_payout_attempts",
        type_="unique",
    )
    op.drop_index(
        "ix_affiliate_payout_attempts_status",
        table_name="affiliate_payout_attempts",
    )
    op.drop_index(
        "ix_affiliate_payout_attempts_payout_id",
        table_name="affiliate_payout_attempts",
    )

    # ---------------------------------------------------------
    # affiliate_opportunities
    # ---------------------------------------------------------
    op.drop_index(
        "ix_affiliate_opportunities_product_id",
        table_name="affiliate_opportunities",
    )

    # ---------------------------------------------------------
    # affiliate_links
    # ---------------------------------------------------------
    op.drop_constraint(
        "affiliate_links_content_asset_id_fkey",
        "affiliate_links",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_affiliate_links_tracking_code",
        table_name="affiliate_links",
    )

    # ---------------------------------------------------------
    # affiliate_earnings
    # ---------------------------------------------------------
    op.drop_constraint(
        "affiliate_earnings_payout_id_fkey",
        "affiliate_earnings",
        type_="foreignkey",
    )

    op.drop_constraint(
        "affiliate_earnings_conversion_id_fkey",
        "affiliate_earnings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "affiliate_earnings_affiliate_program_id_fkey",
        "affiliate_earnings",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "affiliate_earnings_conversion_id_fkey",
        "affiliate_earnings",
        "affiliate_conversions",
        ["conversion_id"],
        ["id"],
    )
    op.create_foreign_key(
        "affiliate_earnings_affiliate_program_id_fkey",
        "affiliate_earnings",
        "affiliate_programs",
        ["affiliate_program_id"],
        ["id"],
    )

    op.drop_constraint(
        "uq_affiliate_earning_conversion_id",
        "affiliate_earnings",
        type_="unique",
    )
    op.drop_index(
        "ix_affiliate_earnings_payout_id",
        table_name="affiliate_earnings",
    )
    op.drop_index(
        "ix_affiliate_earnings_conversion_id",
        table_name="affiliate_earnings",
    )
    op.drop_index(
        "ix_affiliate_earnings_affiliate_program_id",
        table_name="affiliate_earnings",
    )

    # ---------------------------------------------------------
    # affiliate_conversions
    # ---------------------------------------------------------
    op.drop_constraint(
        "affiliate_conversions_affiliate_program_id_fkey",
        "affiliate_conversions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "affiliate_conversions_affiliate_link_id_fkey",
        "affiliate_conversions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "affiliate_conversions_affiliate_program_id_fkey",
        "affiliate_conversions",
        "affiliate_programs",
        ["affiliate_program_id"],
        ["id"],
    )
    op.create_foreign_key(
        "affiliate_conversions_affiliate_link_id_fkey",
        "affiliate_conversions",
        "affiliate_links",
        ["affiliate_link_id"],
        ["id"],
    )

    op.drop_constraint(
        "uq_affiliate_conversion_external_id",
        "affiliate_conversions",
        type_="unique",
    )
    op.drop_index(
        "ix_affiliate_conversions_external_conversion_id",
        table_name="affiliate_conversions",
    )
    op.drop_index(
        "ix_affiliate_conversions_affiliate_program_id",
        table_name="affiliate_conversions",
    )
    op.drop_index(
        "ix_affiliate_conversions_affiliate_link_id",
        table_name="affiliate_conversions",
    )

    # ---------------------------------------------------------
    # affiliate_content_assets
    # ---------------------------------------------------------
    op.drop_index(
        "ix_affiliate_content_assets_product_id",
        table_name="affiliate_content_assets",
    )


    _revert_publishing_queue_asset_channel_unique()
