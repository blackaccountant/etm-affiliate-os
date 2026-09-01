"""add public attribution bridge

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "affiliate_links",
        sa.Column("attribution_context_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_affiliate_links_attribution_context_id",
        "affiliate_links",
        "attribution_contexts",
        ["attribution_context_id"],
        ["id"],
    )
    op.create_index(
        "ix_affiliate_links_attribution_context_id",
        "affiliate_links",
        ["attribution_context_id"],
    )
    op.create_index(
        "uq_affiliate_links_attributed_tracking_code",
        "affiliate_links",
        ["tracking_code"],
        unique=True,
        postgresql_where=sa.text("attribution_context_id IS NOT NULL"),
    )

    op.add_column(
        "affiliate_clicks",
        sa.Column("attribution_click_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_affiliate_clicks_attribution_click_id",
        "affiliate_clicks",
        "attribution_clicks",
        ["attribution_click_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_affiliate_clicks_attribution_click_id",
        "affiliate_clicks",
        ["attribution_click_id"],
    )

    op.execute("""
        CREATE FUNCTION m10a3_reject_link_context_rebinding() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.attribution_context_id IS NOT NULL
               AND NEW.attribution_context_id IS DISTINCT FROM OLD.attribution_context_id THEN
                RAISE EXCEPTION 'attribution context binding is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_m10a3_affiliate_link_context_immutable
        BEFORE UPDATE OF attribution_context_id ON affiliate_links
        FOR EACH ROW EXECUTE FUNCTION m10a3_reject_link_context_rebinding()
    """)
    op.execute("""
        CREATE FUNCTION m10a3_reject_click_correlation_rebinding() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.attribution_click_id IS NOT NULL
               AND NEW.attribution_click_id IS DISTINCT FROM OLD.attribution_click_id THEN
                RAISE EXCEPTION 'attribution click correlation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_m10a3_affiliate_click_correlation_immutable
        BEFORE UPDATE OF attribution_click_id ON affiliate_clicks
        FOR EACH ROW EXECUTE FUNCTION m10a3_reject_click_correlation_rebinding()
    """)


def downgrade():
    op.execute(
        "DROP TRIGGER IF EXISTS trg_m10a3_affiliate_click_correlation_immutable "
        "ON affiliate_clicks"
    )
    op.execute("DROP FUNCTION IF EXISTS m10a3_reject_click_correlation_rebinding()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_m10a3_affiliate_link_context_immutable "
        "ON affiliate_links"
    )
    op.execute("DROP FUNCTION IF EXISTS m10a3_reject_link_context_rebinding()")

    op.drop_constraint(
        "uq_affiliate_clicks_attribution_click_id",
        "affiliate_clicks",
        type_="unique",
    )
    op.drop_constraint(
        "fk_affiliate_clicks_attribution_click_id",
        "affiliate_clicks",
        type_="foreignkey",
    )
    op.drop_column("affiliate_clicks", "attribution_click_id")

    op.drop_index(
        "uq_affiliate_links_attributed_tracking_code",
        table_name="affiliate_links",
    )
    op.drop_index(
        "ix_affiliate_links_attribution_context_id",
        table_name="affiliate_links",
    )
    op.drop_constraint(
        "fk_affiliate_links_attribution_context_id",
        "affiliate_links",
        type_="foreignkey",
    )
    op.drop_column("affiliate_links", "attribution_context_id")
