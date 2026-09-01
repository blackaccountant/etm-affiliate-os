"""add attribution earning links

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime


revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attribution_earning_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("attribution_fact_id", sa.String(36), sa.ForeignKey("attribution_facts.id"), nullable=False),
        sa.Column("affiliate_conversion_id", sa.Integer(), sa.ForeignKey("affiliate_conversions.id"), nullable=False),
        sa.Column("affiliate_earning_id", sa.Integer(), sa.ForeignKey("affiliate_earnings.id"), nullable=False),
        sa.Column("source_namespace", sa.String(63), nullable=False),
        sa.Column("source_event_key_digest", sa.String(64), nullable=False),
        sa.Column("linkage_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'", name="ck_attribution_earning_links_namespace"),
        sa.CheckConstraint("source_event_key_digest ~ '^[0-9a-f]{64}$'", name="ck_attribution_earning_links_source_digest"),
        sa.CheckConstraint("linkage_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_attribution_earning_links_fingerprint"),
        sa.UniqueConstraint("attribution_fact_id", name="uq_attribution_earning_links_fact"),
        sa.UniqueConstraint("affiliate_conversion_id", name="uq_attribution_earning_links_conversion"),
        sa.UniqueConstraint("affiliate_earning_id", name="uq_attribution_earning_links_earning"),
        sa.UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_earning_links_source"),
    )
    op.create_index("ix_attribution_earning_links_earning", "attribution_earning_links", ["affiliate_earning_id"])
    op.execute("""
        CREATE FUNCTION m10a4_validate_attribution_earning_link() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE fact_conversion integer; earning_conversion integer;
        BEGIN
            SELECT affiliate_conversion_id INTO fact_conversion
            FROM attribution_facts
            WHERE id = NEW.attribution_fact_id AND fact_kind = 'CONVERSION_REPORTED';
            IF fact_conversion IS NULL OR fact_conversion <> NEW.affiliate_conversion_id THEN
                RAISE EXCEPTION 'earning linkage must match a CONVERSION_REPORTED attribution fact';
            END IF;
            SELECT conversion_id INTO earning_conversion
            FROM affiliate_earnings WHERE id = NEW.affiliate_earning_id;
            IF earning_conversion IS NULL OR earning_conversion <> NEW.affiliate_conversion_id THEN
                RAISE EXCEPTION 'earning linkage must match authoritative earning conversion';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                NEW.attribution_fact_id IS DISTINCT FROM OLD.attribution_fact_id OR
                NEW.affiliate_conversion_id IS DISTINCT FROM OLD.affiliate_conversion_id OR
                NEW.affiliate_earning_id IS DISTINCT FROM OLD.affiliate_earning_id OR
                NEW.source_namespace IS DISTINCT FROM OLD.source_namespace OR
                NEW.source_event_key_digest IS DISTINCT FROM OLD.source_event_key_digest OR
                NEW.linkage_fingerprint IS DISTINCT FROM OLD.linkage_fingerprint
            ) THEN
                RAISE EXCEPTION 'attribution earning linkage identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_m10a4_attribution_earning_links_validate
        BEFORE INSERT OR UPDATE ON attribution_earning_links
        FOR EACH ROW EXECUTE FUNCTION m10a4_validate_attribution_earning_link()
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_m10a4_attribution_earning_links_validate ON attribution_earning_links")
    op.execute("DROP FUNCTION IF EXISTS m10a4_validate_attribution_earning_link()")
    op.drop_table("attribution_earning_links")
