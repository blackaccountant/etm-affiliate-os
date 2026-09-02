"""add immutable affiliate cost events

Revision ID: a9b0c1d2e3f4
Revises: e7f8a9b0c1d2
"""
from alembic import op
import sqlalchemy as sa
from app.database.types import UTCDateTime

revision = "a9b0c1d2e3f4"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("affiliate_cost_events", sa.Column("id",sa.String(36),primary_key=True),sa.Column("amount",sa.Numeric(18,2),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("cost_type",sa.String(63),nullable=False),sa.Column("allocation_scope",sa.String(16),nullable=False),sa.Column("source_namespace",sa.String(63),nullable=False),sa.Column("source_event_digest",sa.String(64),nullable=False),sa.Column("fingerprint",sa.String(64),nullable=False),sa.Column("product_id",sa.Integer(),sa.ForeignKey("products.id")),sa.Column("affiliate_program_id",sa.Integer(),sa.ForeignKey("affiliate_programs.id")),sa.Column("content_asset_id",sa.Integer(),sa.ForeignKey("affiliate_content_assets.id")),sa.Column("content_generation_run_id",sa.String(36),sa.ForeignKey("content_generation_runs.id")),sa.Column("distribution_run_id",sa.String(36),sa.ForeignKey("distribution_runs.id")),sa.Column("affiliate_link_id",sa.Integer(),sa.ForeignKey("affiliate_links.id")),sa.Column("affiliate_conversion_id",sa.Integer(),sa.ForeignKey("affiliate_conversions.id")),sa.Column("affiliate_earning_id",sa.Integer(),sa.ForeignKey("affiliate_earnings.id")),sa.Column("affiliate_payout_id",sa.Integer(),sa.ForeignKey("affiliate_payouts.id")),sa.Column("affiliate_payout_attempt_id",sa.Integer(),sa.ForeignKey("affiliate_payout_attempts.id")),sa.Column("outreach_provider_dispatch_id",sa.String(36),sa.ForeignKey("outreach_provider_dispatches.id")),sa.Column("created_at",UTCDateTime(),nullable=False),sa.CheckConstraint("amount > 0",name="ck_affiliate_cost_events_positive_amount"),sa.CheckConstraint("allocation_scope IN ('direct','shared','global')",name="ck_affiliate_cost_events_scope"),sa.UniqueConstraint("source_namespace","source_event_digest",name="uq_affiliate_cost_events_source"))
    op.execute("CREATE FUNCTION m10a9a_reject_cost_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'affiliate cost events are append-only'; END; $$")
    op.execute("CREATE TRIGGER trg_m10a9a_cost_event_immutable BEFORE UPDATE OR DELETE ON affiliate_cost_events FOR EACH ROW EXECUTE FUNCTION m10a9a_reject_cost_event_mutation()")

def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_m10a9a_cost_event_immutable ON affiliate_cost_events")
    op.execute("DROP FUNCTION IF EXISTS m10a9a_reject_cost_event_mutation()")
    op.drop_table("affiliate_cost_events")
