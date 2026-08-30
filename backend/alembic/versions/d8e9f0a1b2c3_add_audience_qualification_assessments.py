"""add immutable audience qualification assessments

Revision ID: d8e9f0a1b2c3
Revises: c7d3e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa


revision = "d8e9f0a1b2c3"
down_revision = "c7d3e4f5a6b7"
branch_labels = None
depends_on = None


_DIMENSIONS = ("problem_strength", "interest_alignment", "research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent", "purchase_signal", "engagement", "business_need_fit")
_MEASURES = _DIMENSIONS + ("intent_score", "qualification_score")


def upgrade():
    columns = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("scoring_ruleset_version", sa.String(128), nullable=False),
        sa.Column("scoring_ruleset_fingerprint", sa.String(64), nullable=False),
        sa.Column("scoring_ruleset_json", sa.JSON(), nullable=False),
        sa.Column("context_type", sa.String(16), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("selected_membership_fingerprint", sa.String(64), nullable=False),
        *(sa.Column(field, sa.Integer(), nullable=False) for field in _MEASURES),
        sa.Column("qualification_status", sa.String(32), nullable=False),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["audience_profiles.id"]),
        sa.UniqueConstraint("profile_id", "scoring_ruleset_version", "scoring_ruleset_fingerprint", "context_fingerprint", "selected_membership_fingerprint", name="uq_audience_qualification_assessments_identity"),
        sa.CheckConstraint("length(scoring_ruleset_fingerprint) = 64", name="ck_audience_qualification_assessments_ruleset_fingerprint"),
        sa.CheckConstraint("length(context_fingerprint) = 64", name="ck_audience_qualification_assessments_context_fingerprint"),
        sa.CheckConstraint("length(selected_membership_fingerprint) = 64", name="ck_audience_qualification_assessments_membership_fingerprint"),
        sa.CheckConstraint("context_type IN ('NONE', 'PRODUCT', 'OFFER', 'TOPIC')", name="ck_audience_qualification_assessments_context_type"),
        sa.CheckConstraint("qualification_status IN ('NOT_QUALIFIED', 'EARLY', 'QUALIFIED', 'HIGH_INTENT')", name="ck_audience_qualification_assessments_status"),
        *(sa.CheckConstraint(f"{field} >= 0 AND {field} <= 100", name=f"ck_audience_qualification_assessments_{field}") for field in _MEASURES),
    ]
    op.create_table("audience_qualification_assessments", *columns)
    op.create_index("ix_audience_qualification_assessments_profile", "audience_qualification_assessments", ["profile_id"])
    op.create_table(
        "audience_qualification_assessment_memberships",
        sa.Column("assessment_id", sa.String(36), primary_key=True),
        sa.Column("membership_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(["assessment_id"], ["audience_qualification_assessments.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["audience_segment_memberships.id"]),
    )
    contribution_columns = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("source_signal_id", sa.String(36), nullable=False),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        *(sa.Column(field, sa.Integer(), nullable=False) for field in ("strength", "confidence", "raw_amount", "confidence_adjusted_amount", "final_amount")),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["audience_qualification_assessments.id"]),
        sa.ForeignKeyConstraint(["source_signal_id"], ["audience_signals.id"]),
        sa.UniqueConstraint("assessment_id", "source_signal_id", "dimension", "rule_id", name="uq_audience_qualification_contributions_identity"),
        sa.CheckConstraint("dimension IN ('problem_strength', 'interest_alignment', 'research_intent', 'comparison_intent', 'evaluation_intent', 'pricing_intent', 'purchase_request_intent', 'purchase_signal', 'engagement', 'business_need_fit')", name="ck_aqc_dimension"),
        sa.CheckConstraint("disposition IN ('SELECTED', 'DUPLICATE_SUPPRESSED', 'CAPPED')", name="ck_aqc_disposition"),
        *(sa.CheckConstraint(f"{field} >= 0 AND {field} <= 100", name=f"ck_aqc_{field}") for field in ("strength", "confidence", "raw_amount", "confidence_adjusted_amount", "final_amount")),
    ]
    op.create_table("audience_qualification_contributions", *contribution_columns)
    op.create_index("ix_audience_qualification_contributions_signal", "audience_qualification_contributions", ["source_signal_id"])


def downgrade():
    op.drop_index("ix_audience_qualification_contributions_signal", table_name="audience_qualification_contributions")
    op.drop_table("audience_qualification_contributions")
    op.drop_table("audience_qualification_assessment_memberships")
    op.drop_index("ix_audience_qualification_assessments_profile", table_name="audience_qualification_assessments")
    op.drop_table("audience_qualification_assessments")
