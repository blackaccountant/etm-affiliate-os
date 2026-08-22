"""add content asset versioning

Revision ID: 5f990d3273c8
Revises: 5ae0372b774f
Create Date: 2026-08-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f990d3273c8"

down_revision: Union[str, Sequence[str], None] = "5ae0372b774f"

branch_labels = None
depends_on = None



def upgrade() -> None:
    """
    Add production-grade content versioning support.

    Adds:
    - parent_id     : links content versions together
    - version       : version number
    - is_active     : identifies current published version

    Creates:
    - self-referencing foreign key
    - index for fast version lookup
    """

    # -------------------------------------------------
    # Add parent reference
    # -------------------------------------------------

    op.add_column(
        "affiliate_content_assets",
        sa.Column(
            "parent_id",
            sa.Integer(),
            nullable=True,
        ),
    )


    # -------------------------------------------------
    # Add version number
    # -------------------------------------------------

    op.add_column(
        "affiliate_content_assets",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


    # -------------------------------------------------
    # Active version flag
    # -------------------------------------------------

    op.add_column(
        "affiliate_content_assets",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


    # -------------------------------------------------
    # Self-referencing foreign key
    # affiliate_content_assets.parent_id
    # -> affiliate_content_assets.id
    # -------------------------------------------------

    op.create_foreign_key(
        "fk_affiliate_content_asset_parent",
        "affiliate_content_assets",
        "affiliate_content_assets",
        ["parent_id"],
        ["id"],
    )


    # -------------------------------------------------
    # Indexes
    # -------------------------------------------------

    op.create_index(
        "ix_affiliate_content_assets_parent_id",
        "affiliate_content_assets",
        ["parent_id"],
    )


    op.create_index(
        "ix_affiliate_content_assets_active_version",
        "affiliate_content_assets",
        [
            "product_id",
            "is_active",
        ],
    )



def downgrade() -> None:
    """
    Remove content versioning support.
    """

    # Remove indexes

    op.drop_index(
        "ix_affiliate_content_assets_active_version",
        table_name="affiliate_content_assets",
    )


    op.drop_index(
        "ix_affiliate_content_assets_parent_id",
        table_name="affiliate_content_assets",
    )


    # Remove foreign key

    op.drop_constraint(
        "fk_affiliate_content_asset_parent",
        "affiliate_content_assets",
        type_="foreignkey",
    )


    # Remove columns

    op.drop_column(
        "affiliate_content_assets",
        "is_active",
    )


    op.drop_column(
        "affiliate_content_assets",
        "version",
    )


    op.drop_column(
        "affiliate_content_assets",
        "parent_id",
    )
