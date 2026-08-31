"""add cold B2B prospecting authorizations

Revision ID: c1d2e3f4a5b6
Revises: c0d1e2f3a4b5
"""

from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("cold_prospecting_organization_evidence", sa.Column("id", sa.String(36), nullable=False), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("source_namespace", sa.String(100), nullable=False), sa.Column("source_event_key", sa.String(512), nullable=False), sa.Column("evidence_reference", sa.Text(), nullable=False), sa.Column("evidence_fingerprint", sa.String(64), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("length(trim(source_namespace)) > 0 AND length(source_namespace) <= 100", name="ck_cold_org_evidence_namespace"), sa.CheckConstraint("length(trim(source_event_key)) > 0 AND length(source_event_key) <= 512", name="ck_cold_org_evidence_source_key"), sa.CheckConstraint("length(trim(evidence_reference)) > 0 AND length(evidence_reference) <= 512", name="ck_cold_org_evidence_reference"), sa.CheckConstraint("length(evidence_fingerprint) = 64", name="ck_cold_org_evidence_fingerprint"), sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_cold_org_evidence_request_fingerprint"), sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_org_evidence_source"))
    op.create_index("ix_cold_org_evidence_lead", "cold_prospecting_organization_evidence", ["lead_id"])
    op.create_table("cold_prospecting_authorizations", sa.Column("id", sa.String(36), nullable=False), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("contact_point_id", sa.String(36), nullable=False), sa.Column("organization_evidence_id", sa.String(36), nullable=False), sa.Column("channel", sa.String(32), nullable=False), sa.Column("purpose_key", sa.String(128), nullable=False), sa.Column("purpose_family", sa.String(128), nullable=False), sa.Column("requested_action", sa.String(32), nullable=False), sa.Column("source_namespace", sa.String(100), nullable=False), sa.Column("source_event_key", sa.String(512), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False), sa.Column("authorization_state", sa.String(32), nullable=False), sa.Column("reason_codes", sa.JSON(), nullable=False), sa.Column("eligibility_policy_version", sa.String(128), nullable=False), sa.Column("frequency_policy_version", sa.String(128), nullable=False), sa.Column("policy_profile_key", sa.String(128), nullable=False), sa.Column("decision_fingerprint", sa.String(64), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("channel = 'EMAIL'", name="ck_cold_authorizations_email"), sa.CheckConstraint("purpose_key LIKE 'cold_b2b:%'", name="ck_cold_authorizations_purpose"), sa.CheckConstraint("requested_action IN ('INITIAL','FOLLOW_UP')", name="ck_cold_authorizations_action"), sa.CheckConstraint("authorization_state IN ('ELIGIBLE','INELIGIBLE','POLICY_UNAVAILABLE')", name="ck_cold_authorizations_state"), sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_cold_authorizations_request_fingerprint"), sa.CheckConstraint("length(decision_fingerprint) = 64", name="ck_cold_authorizations_decision_fingerprint"), sa.CheckConstraint("length(trim(policy_profile_key)) > 0 AND length(policy_profile_key) <= 128", name="ck_cold_authorizations_policy_key"), sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]), sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]), sa.ForeignKeyConstraint(["organization_evidence_id"], ["cold_prospecting_organization_evidence.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_authorizations_source"))
    op.create_index("ix_cold_authorizations_frequency", "cold_prospecting_authorizations", ["lead_id", "contact_point_id", "channel", "purpose_family", "evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_cold_authorizations_frequency", table_name="cold_prospecting_authorizations")
    op.drop_table("cold_prospecting_authorizations")
    op.drop_index("ix_cold_org_evidence_lead", table_name="cold_prospecting_organization_evidence")
    op.drop_table("cold_prospecting_organization_evidence")
