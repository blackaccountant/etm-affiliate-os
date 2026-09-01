"""add attribution payout settlement links

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime


revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attribution_payout_settlement_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("attribution_earning_link_id", sa.String(36), sa.ForeignKey("attribution_earning_links.id"), nullable=False),
        sa.Column("affiliate_earning_id", sa.Integer(), sa.ForeignKey("affiliate_earnings.id"), nullable=False),
        sa.Column("affiliate_payout_id", sa.Integer(), sa.ForeignKey("affiliate_payouts.id"), nullable=False),
        sa.Column("affiliate_payout_attempt_id", sa.Integer(), sa.ForeignKey("affiliate_payout_attempts.id"), nullable=False),
        sa.Column("source_namespace", sa.String(63), nullable=False),
        sa.Column("source_event_key_digest", sa.String(64), nullable=False),
        sa.Column("linkage_fingerprint", sa.String(64), nullable=False),
        sa.Column("observed_at", UTCDateTime(), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'", name="ck_attribution_payout_settlement_links_namespace"),
        sa.CheckConstraint("source_event_key_digest ~ '^[0-9a-f]{64}$'", name="ck_attribution_payout_settlement_links_source_digest"),
        sa.CheckConstraint("linkage_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_attribution_payout_settlement_links_fingerprint"),
        sa.UniqueConstraint("attribution_earning_link_id", name="uq_attribution_payout_settlement_links_earning_link"),
        sa.UniqueConstraint("affiliate_earning_id", name="uq_attribution_payout_settlement_links_earning"),
        sa.UniqueConstraint("affiliate_earning_id", "affiliate_payout_id", "affiliate_payout_attempt_id", name="uq_attribution_payout_settlement_links_lineage"),
        sa.UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_payout_settlement_links_source"),
    )
    op.create_index("ix_attribution_payout_settlement_links_payout", "attribution_payout_settlement_links", ["affiliate_payout_id"])
    op.create_index("ix_attribution_payout_settlement_links_attempt", "attribution_payout_settlement_links", ["affiliate_payout_attempt_id"])
    op.execute("""
        CREATE FUNCTION m10a5_validate_attribution_payout_settlement_link() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE linked_earning integer; earning_payout integer; earning_status text;
                payout_status text; attempt_payout integer; attempt_status text; completed_count integer;
        BEGIN
            SELECT affiliate_earning_id INTO linked_earning
            FROM attribution_earning_links WHERE id = NEW.attribution_earning_link_id;
            IF linked_earning IS NULL OR linked_earning <> NEW.affiliate_earning_id THEN
                RAISE EXCEPTION 'settlement link must match attribution earning link';
            END IF;
            SELECT payout_id, status INTO earning_payout, earning_status
            FROM affiliate_earnings WHERE id = NEW.affiliate_earning_id;
            IF earning_payout IS NULL OR earning_payout <> NEW.affiliate_payout_id OR earning_status <> 'paid' THEN
                RAISE EXCEPTION 'settlement link requires paid earning assigned to payout';
            END IF;
            SELECT status INTO payout_status FROM affiliate_payouts WHERE id = NEW.affiliate_payout_id;
            IF payout_status IS NULL OR payout_status <> 'paid' THEN
                RAISE EXCEPTION 'settlement link requires paid payout';
            END IF;
            SELECT payout_id, status INTO attempt_payout, attempt_status
            FROM affiliate_payout_attempts WHERE id = NEW.affiliate_payout_attempt_id;
            SELECT count(*) INTO completed_count FROM affiliate_payout_attempts
            WHERE payout_id = NEW.affiliate_payout_id AND status = 'completed';
            IF attempt_payout IS NULL OR attempt_payout <> NEW.affiliate_payout_id
               OR attempt_status <> 'completed' OR completed_count <> 1 THEN
                RAISE EXCEPTION 'settlement link requires exactly one completed payout attempt';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                NEW.attribution_earning_link_id IS DISTINCT FROM OLD.attribution_earning_link_id OR
                NEW.affiliate_earning_id IS DISTINCT FROM OLD.affiliate_earning_id OR
                NEW.affiliate_payout_id IS DISTINCT FROM OLD.affiliate_payout_id OR
                NEW.affiliate_payout_attempt_id IS DISTINCT FROM OLD.affiliate_payout_attempt_id OR
                NEW.source_namespace IS DISTINCT FROM OLD.source_namespace OR
                NEW.source_event_key_digest IS DISTINCT FROM OLD.source_event_key_digest OR
                NEW.linkage_fingerprint IS DISTINCT FROM OLD.linkage_fingerprint
            ) THEN
                RAISE EXCEPTION 'attribution payout settlement linkage identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_m10a5_attribution_payout_settlement_links_validate
        BEFORE INSERT OR UPDATE ON attribution_payout_settlement_links
        FOR EACH ROW EXECUTE FUNCTION m10a5_validate_attribution_payout_settlement_link()
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_m10a5_attribution_payout_settlement_links_validate ON attribution_payout_settlement_links")
    op.execute("DROP FUNCTION IF EXISTS m10a5_validate_attribution_payout_settlement_link()")
    op.drop_table("attribution_payout_settlement_links")
