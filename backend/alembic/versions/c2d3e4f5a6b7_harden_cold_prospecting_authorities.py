"""harden immutable cold prospecting authorities

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

_TABLES = ("cold_prospecting_organization_evidence", "cold_prospecting_policy_selections", "cold_prospecting_authorizations")


def upgrade() -> None:
    op.add_column("cold_prospecting_organization_evidence", sa.Column("source_classification", sa.String(64), nullable=True))
    op.add_column("cold_prospecting_organization_evidence", sa.Column("source_record_fingerprint", sa.String(64), nullable=True))
    op.add_column("cold_prospecting_organization_evidence", sa.Column("acceptance_state", sa.String(32), nullable=True))
    op.add_column("cold_prospecting_organization_evidence", sa.Column("evidence_schema_version", sa.String(128), nullable=True))
    op.add_column("cold_prospecting_organization_evidence", sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_cold_org_evidence_id_lead", "cold_prospecting_organization_evidence", ["id", "lead_id"])
    op.create_check_constraint("ck_cold_org_evidence_authority", "cold_prospecting_organization_evidence", "acceptance_state IS NULL OR (acceptance_state='ACCEPTED' AND source_classification IN ('ORGANIZATION_REGISTRY','VERIFIED_BUSINESS_SOURCE') AND length(source_record_fingerprint)=64 AND evidence_reference=source_record_fingerprint AND length(trim(evidence_schema_version)) > 0)")
    op.create_table("cold_prospecting_policy_selections", sa.Column("id", sa.String(36), nullable=False), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("source_namespace", sa.String(100), nullable=False), sa.Column("source_event_key", sa.String(512), nullable=False), sa.Column("evidence_fingerprint", sa.String(64), nullable=False), sa.Column("profile_key", sa.String(128), nullable=False), sa.Column("profile_version", sa.String(128), nullable=False), sa.Column("acceptance_state", sa.String(32), nullable=False), sa.Column("selection_schema_version", sa.String(128), nullable=False), sa.Column("decision_fingerprint", sa.String(64), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("acceptance_state IN ('ACCEPTED','REJECTED')", name="ck_cold_policy_selection_acceptance"), sa.CheckConstraint("length(evidence_fingerprint)=64", name="ck_cold_policy_selection_evidence_fingerprint"), sa.CheckConstraint("length(decision_fingerprint)=64", name="ck_cold_policy_selection_decision_fingerprint"), sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_namespace", "source_event_key", name="uq_cold_policy_selection_source"), sa.UniqueConstraint("id", "lead_id", name="uq_cold_policy_selection_id_lead"))
    op.create_index("ix_cold_policy_selection_lead", "cold_prospecting_policy_selections", ["lead_id"])
    op.add_column("cold_prospecting_authorizations", sa.Column("policy_selection_id", sa.String(36), nullable=True))
    op.alter_column("cold_prospecting_authorizations", "organization_evidence_id", existing_type=sa.String(36), nullable=True)
    op.create_foreign_key("fk_cold_authorizations_org_owner", "cold_prospecting_authorizations", "cold_prospecting_organization_evidence", ["organization_evidence_id", "lead_id"], ["id", "lead_id"])
    op.create_foreign_key("fk_cold_authorizations_policy_owner", "cold_prospecting_authorizations", "cold_prospecting_policy_selections", ["policy_selection_id", "lead_id"], ["id", "lead_id"])
    op.execute("""CREATE FUNCTION prevent_cold_prospecting_authority_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'cold prospecting authority records are append-only'; END; $$""")
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_cold_prospecting_authority_mutation()")


def downgrade() -> None:
    for table in reversed(_TABLES): op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_cold_prospecting_authority_mutation()")
    op.drop_constraint("fk_cold_authorizations_policy_owner", "cold_prospecting_authorizations", type_="foreignkey")
    op.drop_constraint("fk_cold_authorizations_org_owner", "cold_prospecting_authorizations", type_="foreignkey")
    op.alter_column("cold_prospecting_authorizations", "organization_evidence_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("cold_prospecting_authorizations", "policy_selection_id")
    op.drop_index("ix_cold_policy_selection_lead", table_name="cold_prospecting_policy_selections")
    op.drop_table("cold_prospecting_policy_selections")
    op.drop_constraint("ck_cold_org_evidence_authority", "cold_prospecting_organization_evidence", type_="check")
    op.drop_constraint("uq_cold_org_evidence_id_lead", "cold_prospecting_organization_evidence", type_="unique")
    for column in ("evaluated_at", "evidence_schema_version", "acceptance_state", "source_record_fingerprint", "source_classification"):
        op.drop_column("cold_prospecting_organization_evidence", column)
