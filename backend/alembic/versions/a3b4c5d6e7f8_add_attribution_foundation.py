"""add additive attribution foundation

Revision ID: a3b4c5d6e7f8
Revises: f2e3d4c5b6a7
"""

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime


revision = "a3b4c5d6e7f8"
down_revision = "f2e3d4c5b6a7"
branch_labels = None
depends_on = None


_FACT_REFERENCE_CHECK = """
(
 fact_kind = 'PUBLICATION_BOUND'
 AND attribution_publication_id IS NOT NULL
 AND attribution_context_id IS NULL AND attribution_click_id IS NULL
 AND affiliate_link_id IS NULL AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'LINK_BOUND'
 AND attribution_context_id IS NOT NULL AND affiliate_link_id IS NOT NULL
 AND attribution_publication_id IS NULL AND attribution_click_id IS NULL
 AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'CLICK_RECORDED'
 AND attribution_context_id IS NOT NULL AND attribution_click_id IS NOT NULL AND affiliate_link_id IS NOT NULL
 AND attribution_publication_id IS NULL AND affiliate_conversion_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'CONVERSION_REPORTED'
 AND attribution_context_id IS NOT NULL AND affiliate_conversion_id IS NOT NULL
 AND attribution_publication_id IS NULL AND supersedes_fact_id IS NULL
) OR (
 fact_kind = 'ATTRIBUTION_CORRECTED' AND supersedes_fact_id IS NOT NULL
)
"""


def upgrade():
    op.create_table(
        "attribution_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("legacy_publishing_queue_id", sa.Integer(), sa.ForeignKey("publishing_queue.id"), nullable=True),
        sa.Column("distribution_run_id", sa.String(36), sa.ForeignKey("distribution_runs.id"), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(legacy_publishing_queue_id, distribution_run_id) = 1",
            name="ck_attribution_publications_one_authority",
        ),
        sa.UniqueConstraint("legacy_publishing_queue_id", name="uq_attribution_publications_legacy_queue"),
        sa.UniqueConstraint("distribution_run_id", name="uq_attribution_publications_distribution_run"),
    )
    op.create_table(
        "attribution_contexts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("affiliate_program_id", sa.Integer(), sa.ForeignKey("affiliate_programs.id"), nullable=False),
        sa.Column("attribution_publication_id", sa.String(36), sa.ForeignKey("attribution_publications.id"), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("context_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_attribution_contexts_fingerprint"),
        sa.UniqueConstraint("context_fingerprint", name="uq_attribution_contexts_fingerprint"),
    )
    op.create_index("ix_attribution_contexts_program", "attribution_contexts", ["affiliate_program_id"])
    op.create_index("ix_attribution_contexts_publication", "attribution_contexts", ["attribution_publication_id"])
    op.create_table(
        "attribution_clicks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("click_key", sa.String(64), nullable=False),
        sa.Column("attribution_context_id", sa.String(36), sa.ForeignKey("attribution_contexts.id"), nullable=False),
        sa.Column("affiliate_link_id", sa.Integer(), sa.ForeignKey("affiliate_links.id"), nullable=False),
        sa.Column("source_namespace", sa.String(63), nullable=False),
        sa.Column("source_event_key_digest", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_attribution_clicks_fingerprint"),
        sa.CheckConstraint("source_event_key_digest ~ '^[0-9a-f]{64}$'", name="ck_attribution_clicks_source_digest"),
        sa.CheckConstraint("source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'", name="ck_attribution_clicks_namespace"),
        sa.UniqueConstraint("click_key", name="uq_attribution_clicks_click_key"),
        sa.UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_clicks_source"),
    )
    op.create_index("ix_attribution_clicks_context", "attribution_clicks", ["attribution_context_id"])
    op.create_index("ix_attribution_clicks_link", "attribution_clicks", ["affiliate_link_id"])
    op.create_index("ix_attribution_clicks_occurred", "attribution_clicks", ["occurred_at"])
    op.create_table(
        "attribution_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fact_kind", sa.String(32), nullable=False),
        sa.Column("source_namespace", sa.String(63), nullable=False),
        sa.Column("source_event_key_digest", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("attribution_publication_id", sa.String(36), sa.ForeignKey("attribution_publications.id"), nullable=True),
        sa.Column("attribution_context_id", sa.String(36), sa.ForeignKey("attribution_contexts.id"), nullable=True),
        sa.Column("attribution_click_id", sa.String(36), sa.ForeignKey("attribution_clicks.id"), nullable=True),
        sa.Column("affiliate_link_id", sa.Integer(), sa.ForeignKey("affiliate_links.id"), nullable=True),
        sa.Column("affiliate_conversion_id", sa.Integer(), sa.ForeignKey("affiliate_conversions.id"), nullable=True),
        sa.Column("supersedes_fact_id", sa.String(36), sa.ForeignKey("attribution_facts.id"), nullable=True),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "fact_kind IN ('PUBLICATION_BOUND','LINK_BOUND','CLICK_RECORDED','CONVERSION_REPORTED','ATTRIBUTION_CORRECTED')",
            name="ck_attribution_facts_kind",
        ),
        sa.CheckConstraint(_FACT_REFERENCE_CHECK, name="ck_attribution_facts_references"),
        sa.CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_attribution_facts_fingerprint"),
        sa.CheckConstraint("source_event_key_digest ~ '^[0-9a-f]{64}$'", name="ck_attribution_facts_source_digest"),
        sa.CheckConstraint("source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'", name="ck_attribution_facts_namespace"),
        sa.CheckConstraint("supersedes_fact_id IS NULL OR supersedes_fact_id <> id", name="ck_attribution_facts_no_self_supersede"),
        sa.UniqueConstraint("source_namespace", "source_event_key_digest", name="uq_attribution_facts_source"),
    )
    op.create_index("ix_attribution_facts_kind_occurred", "attribution_facts", ["fact_kind", "occurred_at"])
    for suffix, column in (
        ("publication", "attribution_publication_id"),
        ("context", "attribution_context_id"),
        ("click", "attribution_click_id"),
        ("link", "affiliate_link_id"),
        ("conversion", "affiliate_conversion_id"),
        ("supersedes", "supersedes_fact_id"),
    ):
        op.create_index(f"ix_attribution_facts_{suffix}", "attribution_facts", [column])
    op.execute("""
        CREATE FUNCTION m10a2_reject_attribution_fact_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'attribution facts are append-only';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_attribution_facts_append_only
        BEFORE UPDATE OR DELETE ON attribution_facts
        FOR EACH ROW EXECUTE FUNCTION m10a2_reject_attribution_fact_mutation()
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_attribution_facts_append_only ON attribution_facts")
    op.execute("DROP FUNCTION IF EXISTS m10a2_reject_attribution_fact_mutation()")
    op.drop_table("attribution_facts")
    op.drop_table("attribution_clicks")
    op.drop_table("attribution_contexts")
    op.drop_table("attribution_publications")
