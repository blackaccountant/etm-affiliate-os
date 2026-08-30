"""add immutable audience profiles and segment revisions

Revision ID: c7d3e4f5a6b7
Revises: b6c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d3e4f5a6b7"
down_revision = "b6c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("audience_profiles", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject_id", sa.String(36), nullable=False), sa.Column("profile_ruleset_version", sa.String(128), nullable=False), sa.Column("source_fingerprint", sa.String(64), nullable=False), sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False), sa.Column("effective_as_of", sa.DateTime(timezone=True), nullable=False), sa.Column("last_signal_observed_at", sa.DateTime(timezone=True)), sa.Column("summary_json", sa.JSON(), nullable=False), sa.ForeignKeyConstraint(["subject_id"], ["audience_subjects.id"]), sa.UniqueConstraint("subject_id", "profile_ruleset_version", "source_fingerprint", name="uq_audience_profiles_identity"), sa.CheckConstraint("length(trim(profile_ruleset_version)) > 0", name="ck_audience_profiles_ruleset"), sa.CheckConstraint("length(trim(source_fingerprint)) = 64", name="ck_audience_profiles_fingerprint"))
    op.create_index("ix_audience_profiles_subject_derived", "audience_profiles", ["subject_id", "derived_at"])
    op.create_table("audience_profile_signals", sa.Column("profile_id", sa.String(36), primary_key=True), sa.Column("signal_id", sa.String(36), primary_key=True), sa.ForeignKeyConstraint(["profile_id"], ["audience_profiles.id"]), sa.ForeignKeyConstraint(["signal_id"], ["audience_signals.id"]))
    op.create_index("ix_audience_profile_signals_signal_id", "audience_profile_signals", ["signal_id"])
    op.create_table("audience_segments", sa.Column("id", sa.String(36), primary_key=True), sa.Column("segment_key", sa.String(128), nullable=False), sa.Column("name", sa.String(256), nullable=False), sa.Column("description", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("retired_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("segment_key", name="uq_audience_segments_key"), sa.CheckConstraint("length(trim(segment_key)) > 0", name="ck_audience_segments_key"))
    op.create_table("audience_segment_revisions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("segment_id", sa.String(36), nullable=False), sa.Column("revision_number", sa.Integer(), nullable=False), sa.Column("segment_ruleset_version", sa.String(128), nullable=False), sa.Column("definition_fingerprint", sa.String(64), nullable=False), sa.Column("definition_json", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["segment_id"], ["audience_segments.id"]), sa.UniqueConstraint("segment_id", "revision_number", name="uq_audience_segment_revisions_number"), sa.UniqueConstraint("segment_id", "segment_ruleset_version", "definition_fingerprint", name="uq_audience_segment_revisions_identity"), sa.CheckConstraint("revision_number > 0", name="ck_audience_segment_revisions_number"), sa.CheckConstraint("length(trim(segment_ruleset_version)) > 0", name="ck_audience_segment_revisions_ruleset"), sa.CheckConstraint("length(trim(definition_fingerprint)) = 64", name="ck_audience_segment_revisions_fingerprint"))
    op.create_index("ix_audience_segment_revisions_segment_number", "audience_segment_revisions", ["segment_id", "revision_number"])
    op.create_table("audience_segment_memberships", sa.Column("id", sa.String(36), primary_key=True), sa.Column("segment_revision_id", sa.String(36), nullable=False), sa.Column("profile_id", sa.String(36), nullable=False), sa.Column("is_member", sa.Boolean(), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["segment_revision_id"], ["audience_segment_revisions.id"]), sa.ForeignKeyConstraint(["profile_id"], ["audience_profiles.id"]), sa.UniqueConstraint("segment_revision_id", "profile_id", name="uq_audience_segment_memberships_identity"))
    op.create_index("ix_audience_segment_memberships_profile_id", "audience_segment_memberships", ["profile_id"])
    op.create_index("ix_audience_segment_memberships_revision_id", "audience_segment_memberships", ["segment_revision_id"])


def downgrade():
    op.drop_index("ix_audience_segment_memberships_revision_id", table_name="audience_segment_memberships")
    op.drop_index("ix_audience_segment_memberships_profile_id", table_name="audience_segment_memberships")
    op.drop_table("audience_segment_memberships")
    op.drop_index("ix_audience_segment_revisions_segment_number", table_name="audience_segment_revisions")
    op.drop_table("audience_segment_revisions")
    op.drop_table("audience_segments")
    op.drop_index("ix_audience_profile_signals_signal_id", table_name="audience_profile_signals")
    op.drop_table("audience_profile_signals")
    op.drop_index("ix_audience_profiles_subject_derived", table_name="audience_profiles")
    op.drop_table("audience_profiles")
