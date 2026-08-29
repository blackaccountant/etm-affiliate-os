"""add content evaluations"""
from alembic import op
import sqlalchemy as sa
revision="e5f6a7b8c9d0"
down_revision="d4e5f6a7b8c9"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("content_evaluations",
        sa.Column("id",sa.String(36),primary_key=True), sa.Column("artifact_id",sa.String(36),sa.ForeignKey("generated_content_artifacts.id"),nullable=False), sa.Column("content_brief_id",sa.String(36),sa.ForeignKey("content_briefs.id"),nullable=False), sa.Column("generation_run_id",sa.String(36),sa.ForeignKey("content_generation_runs.id"),nullable=False),
        *[sa.Column(name,sa.Integer,nullable=False) for name in ("factual_grounding_score","offer_alignment_score","intent_alignment_score","clarity_score","cta_score","compliance_score","overall_score")], sa.Column("decision",sa.String(32),nullable=False),sa.Column("approved",sa.Boolean,nullable=False),sa.Column("evaluator_version",sa.String(100),nullable=False),sa.Column("policy_version",sa.String(100),nullable=False),
        *[sa.Column(name,sa.JSON,nullable=False) for name in ("claim_results","compliance_flags","unsupported_claims","missing_evidence_ids","revision_reasons","rejection_reasons")], sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("artifact_id","evaluator_version","policy_version",name="uq_content_evaluations_identity"))
    for name, columns in (("ix_content_evaluations_artifact_id",["artifact_id"]),("ix_content_evaluations_decision",["decision"]),("ix_content_evaluations_evaluator_version",["evaluator_version"]),("ix_content_evaluations_policy_version",["policy_version"])): op.create_index(name,"content_evaluations",columns)
def downgrade(): op.drop_table("content_evaluations")
