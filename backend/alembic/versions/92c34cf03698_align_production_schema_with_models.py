"""align production schema with models

Revision ID: 92c34cf03698
Revises: 560582ac491a
Create Date: 2026-08-22 00:40:03.775979

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "92c34cf03698"
down_revision: Union[str, Sequence[str], None] = "560582ac491a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align the production database schema with the SQLAlchemy models."""

    # ------------------------------------------------------------------
    # affiliate_content_assets
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_affiliate_content_assets_active_version",
        table_name="affiliate_content_assets",
    )

    op.create_index(
        "ix_affiliate_content_assets_status",
        "affiliate_content_assets",
        ["status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # affiliate_conversions
    # ------------------------------------------------------------------

    op.alter_column(
        "affiliate_conversions",
        "source",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=False,
    )

    op.create_index(
        "ix_affiliate_conversions_conversion_status",
        "affiliate_conversions",
        ["conversion_status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # affiliate_earnings
    # ------------------------------------------------------------------

    op.alter_column(
        "affiliate_earnings",
        "gross_amount",
        existing_type=sa.Numeric(precision=14, scale=2),
        type_=sa.Numeric(precision=18, scale=2),
        existing_nullable=False,
    )

    op.alter_column(
        "affiliate_earnings",
        "commission_rate",
        existing_type=sa.Numeric(precision=10, scale=4),
        nullable=False,
    )

    op.alter_column(
        "affiliate_earnings",
        "commission_amount",
        existing_type=sa.Numeric(precision=14, scale=2),
        type_=sa.Numeric(precision=18, scale=2),
        existing_nullable=False,
    )

    op.alter_column(
        "affiliate_earnings",
        "status",
        existing_type=sa.String(length=50),
        type_=sa.String(length=30),
        existing_nullable=False,
    )

    op.create_index(
        "ix_affiliate_earnings_status",
        "affiliate_earnings",
        ["status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # product_intelligence_history
    # ------------------------------------------------------------------

    op.create_index(
        "ix_product_intelligence_history_fingerprint",
        "product_intelligence_history",
        ["fingerprint"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # products
    # ------------------------------------------------------------------

    op.alter_column(
        "products",
        "category",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )

    op.alter_column(
        "products",
        "affiliate_program",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore the previous production schema."""

    # ------------------------------------------------------------------
    # products
    # ------------------------------------------------------------------

    op.alter_column(
        "products",
        "affiliate_program",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )

    op.alter_column(
        "products",
        "category",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # product_intelligence_history
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_product_intelligence_history_fingerprint",
        table_name="product_intelligence_history",
    )

    # ------------------------------------------------------------------
    # affiliate_earnings
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_affiliate_earnings_status",
        table_name="affiliate_earnings",
    )

    op.alter_column(
        "affiliate_earnings",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

    op.alter_column(
        "affiliate_earnings",
        "commission_amount",
        existing_type=sa.Numeric(precision=18, scale=2),
        type_=sa.Numeric(precision=14, scale=2),
        existing_nullable=False,
    )

    op.alter_column(
        "affiliate_earnings",
        "commission_rate",
        existing_type=sa.Numeric(precision=10, scale=4),
        nullable=True,
    )

    op.alter_column(
        "affiliate_earnings",
        "gross_amount",
        existing_type=sa.Numeric(precision=18, scale=2),
        type_=sa.Numeric(precision=14, scale=2),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # affiliate_conversions
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_affiliate_conversions_conversion_status",
        table_name="affiliate_conversions",
    )

    op.alter_column(
        "affiliate_conversions",
        "source",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # affiliate_content_assets
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_affiliate_content_assets_status",
        table_name="affiliate_content_assets",
    )

    op.create_index(
        "ix_affiliate_content_assets_active_version",
        "affiliate_content_assets",
        ["product_id", "is_active"],
        unique=False,
    )