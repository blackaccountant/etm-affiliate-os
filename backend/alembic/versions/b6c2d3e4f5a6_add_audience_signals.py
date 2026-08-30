"""add immutable audience signals

Revision ID: b6c2d3e4f5a6
Revises: a6b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa
revision = "b6c2d3e4f5a6"
down_revision = "a6b1c2d3e4f5"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("audience_signals", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject_id", sa.String(36)), sa.Column("signal_type", sa.String(32), nullable=False), sa.Column("topic_slug", sa.String(128), nullable=False), sa.Column("topic_label", sa.String(256), nullable=False), sa.Column("intent_stage", sa.String(32)), sa.Column("strength", sa.Integer(), nullable=False), sa.Column("confidence", sa.Integer(), nullable=False), sa.Column("evidence_set_fingerprint", sa.String(64), nullable=False), sa.Column("extraction_key", sa.String(64), nullable=False), sa.Column("ruleset_version", sa.String(128), nullable=False), sa.Column("model_version", sa.String(256)), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("supersedes_signal_id", sa.String(36)), sa.Column("rationale", sa.Text()), sa.Column("metadata_json", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["subject_id"], ["audience_subjects.id"]), sa.ForeignKeyConstraint(["supersedes_signal_id"], ["audience_signals.id"]), sa.UniqueConstraint("extraction_key", name="uq_audience_signals_extraction_key"), sa.CheckConstraint("signal_type IN ('PROBLEM', 'INTEREST', 'INTENT', 'PURCHASE', 'ENGAGEMENT', 'BUSINESS_NEED')", name="ck_audience_signals_type"), sa.CheckConstraint("intent_stage IS NULL OR (signal_type = 'INTENT' AND intent_stage IN ('RESEARCH', 'COMPARE', 'EVALUATE', 'PRICING', 'PURCHASE_REQUEST'))", name="ck_audience_signals_intent_stage"), sa.CheckConstraint("strength >= 0 AND strength <= 100", name="ck_audience_signals_strength"), sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_audience_signals_confidence"), sa.CheckConstraint("length(trim(topic_slug)) > 0", name="ck_audience_signals_topic_slug"), sa.CheckConstraint("length(trim(topic_label)) > 0", name="ck_audience_signals_topic_label"), sa.CheckConstraint("length(trim(ruleset_version)) > 0", name="ck_audience_signals_ruleset"), sa.CheckConstraint("supersedes_signal_id IS NULL OR supersedes_signal_id <> id", name="ck_audience_signals_no_self_supersede"))
    for name, cols in {"ix_audience_signals_subject_id":["subject_id"], "ix_audience_signals_type":["signal_type"], "ix_audience_signals_topic_slug":["topic_slug"], "ix_audience_signals_observed_at":["observed_at"], "ix_audience_signals_derived_at":["derived_at"], "ix_audience_signals_ruleset_version":["ruleset_version"], "ix_audience_signals_supersedes_signal_id":["supersedes_signal_id"]}.items(): op.create_index(name, "audience_signals", cols)
    op.create_table("audience_signal_evidence", sa.Column("signal_id", sa.String(36), primary_key=True), sa.Column("evidence_id", sa.String(36), primary_key=True), sa.ForeignKeyConstraint(["signal_id"], ["audience_signals.id"]), sa.ForeignKeyConstraint(["evidence_id"], ["audience_evidence.id"]), sa.UniqueConstraint("signal_id", "evidence_id", name="uq_audience_signal_evidence_pair"))
    op.create_index("ix_audience_signal_evidence_evidence_id", "audience_signal_evidence", ["evidence_id"])
def downgrade():
    op.drop_index("ix_audience_signal_evidence_evidence_id", table_name="audience_signal_evidence"); op.drop_table("audience_signal_evidence")
    for name in ("ix_audience_signals_supersedes_signal_id", "ix_audience_signals_ruleset_version", "ix_audience_signals_derived_at", "ix_audience_signals_observed_at", "ix_audience_signals_topic_slug", "ix_audience_signals_type", "ix_audience_signals_subject_id"): op.drop_index(name, table_name="audience_signals")
    op.drop_table("audience_signals")
