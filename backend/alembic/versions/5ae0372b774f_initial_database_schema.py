"""Initial database schema.

Revision ID: 5ae0372b774f
Revises:
Create Date: 2026-08-04 06:18:07.883183
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5ae0372b774f"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial ETM Affiliate OS database schema."""

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("affiliate_program", sa.Text(), nullable=False),
        sa.Column("affiliate_url", sa.String(length=1000), nullable=True),
        sa.Column("commission_type", sa.Text(), nullable=False),
        sa.Column("commission_value", sa.Text(), nullable=False),
        sa.Column("cookie_duration", sa.String(length=100), nullable=True),
        sa.Column("affiliate_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grade", sa.String(length=5), nullable=False, server_default="F"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=100), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_products_id",
        "products",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_products_website",
        "products",
        ["website"],
        unique=True,
    )


    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )

    op.create_index(
        "ix_executions_id",
        "executions",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("program_name", sa.String(length=255), nullable=False),
        sa.Column("network", sa.String(length=255), nullable=True),
        sa.Column("program_url", sa.String(length=1000), nullable=True),
        sa.Column("commission_type", sa.Text(), nullable=True),
        sa.Column("commission_value", sa.Text(), nullable=True),
        sa.Column("cookie_duration", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_affiliate_programs_id",
        "affiliate_programs",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("opportunity_grade", sa.String(length=50), nullable=False),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("content_strategy", sa.Text(), nullable=True),
        sa.Column("seo_keywords", sa.Text(), nullable=True),
        sa.Column("promotion_channels", sa.Text(), nullable=True),
        sa.Column("funnel_strategy", sa.Text(), nullable=True),
        sa.Column("revenue_projection", sa.Text(), nullable=True),
        sa.Column("ai_recommendation", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_affiliate_opportunities_id",
        "affiliate_opportunities",
        ["id"],
        unique=False,
    )


    op.create_table(
        "product_intelligence_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=5), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_product_intelligence_history_id",
        "product_intelligence_history",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_content_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("target_keyword", sa.String(length=500), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("search_intent", sa.String(length=100), nullable=True),
        sa.Column("content_outline", sa.Text(), nullable=True),
        sa.Column("call_to_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("seo_title", sa.String(length=500), nullable=True),
        sa.Column("seo_description", sa.Text(), nullable=True),
        sa.Column("published_url", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_affiliate_content_assets_id",
        "affiliate_content_assets",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_program_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_programs.id"),
            nullable=False,
        ),
        sa.Column("content_asset_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("tracking_code", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_affiliate_links_id",
        "affiliate_links",
        ["id"],
        unique=False,
    )


    op.create_table(
        "content_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "content_asset_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_content_assets.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_content_approvals_id",
        "content_approvals",
        ["id"],
        unique=False,
    )


    op.create_table(
        "content_seo_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "content_asset_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_content_assets.id"),
            nullable=False,
        ),
        sa.Column("keyword_score", sa.Integer(), nullable=False),
        sa.Column("search_intent_score", sa.Integer(), nullable=False),
        sa.Column("readability_score", sa.Integer(), nullable=False),
        sa.Column("content_depth_score", sa.Integer(), nullable=False),
        sa.Column("affiliate_fit_score", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("recommendations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_content_seo_scores_id",
        "content_seo_scores",
        ["id"],
        unique=False,
    )


    op.create_table(
        "publishing_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "content_asset_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_content_assets.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("published_url", sa.String(length=1000), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_publishing_queue_id",
        "publishing_queue",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_clicks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_link_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_links.id"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_affiliate_clicks_id",
        "affiliate_clicks",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_link_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_links.id"),
            nullable=True,
        ),
        sa.Column(
            "affiliate_program_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_programs.id"),
            nullable=False,
        ),
        sa.Column("external_conversion_id", sa.String(length=255), nullable=True),
        sa.Column("customer_reference", sa.String(length=255), nullable=True),
        sa.Column("sale_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("conversion_status", sa.String(length=50), nullable=False),
        sa.Column("commission_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("commission_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_affiliate_conversions_id",
        "affiliate_conversions",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_earnings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversion_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_conversions.id"),
            nullable=False,
        ),
        sa.Column(
            "affiliate_program_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_programs.id"),
            nullable=False,
        ),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("commission_rate", sa.Numeric(10, 4), nullable=False),
        sa.Column("commission_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payout_reference", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("payout_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_affiliate_earnings_id",
        "affiliate_earnings",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_payouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_program_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_programs.id"),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("payout_reference", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_index(
        "ix_affiliate_payouts_id",
        "affiliate_payouts",
        ["id"],
        unique=False,
    )


    op.create_table(
        "affiliate_payout_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payout_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_payouts.id"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_affiliate_payout_attempts_id",
        "affiliate_payout_attempts",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the initial ETM Affiliate OS schema."""

    for table in [
        "affiliate_payout_attempts",
        "affiliate_payouts",
        "affiliate_earnings",
        "affiliate_conversions",
        "affiliate_clicks",
        "publishing_queue",
        "content_seo_scores",
        "content_approvals",
        "affiliate_links",
        "affiliate_content_assets",
        "product_intelligence_history",
        "affiliate_opportunities",
        "affiliate_programs",
        "executions",
        "products",
    ]:
        op.drop_table(table)
