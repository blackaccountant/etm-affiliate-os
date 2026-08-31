"""allow blocked T3 decisions without a recipient and bind their operation authority"""

from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_cold_delivery_operations_id_authorization", "cold_delivery_operations", ["id", "cold_authorization_id"])
    op.drop_constraint("ck_cold_t3_decisions_recipient_fingerprint", "cold_t3_decisions", type_="check")
    op.alter_column("cold_t3_decisions", "recipient_fingerprint", existing_type=sa.String(64), nullable=True)
    op.create_check_constraint("ck_cold_t3_decisions_recipient_fingerprint", "cold_t3_decisions", "(decision = 'BLOCKED' AND (recipient_fingerprint IS NULL OR length(recipient_fingerprint) = 64)) OR (decision = 'ALLOWED' AND recipient_fingerprint IS NOT NULL AND length(recipient_fingerprint) = 64)")
    op.create_foreign_key("fk_cold_t3_decisions_operation_authorization", "cold_t3_decisions", "cold_delivery_operations", ["operation_id", "cold_authorization_id"], ["id", "cold_authorization_id"])


def downgrade():
    op.drop_constraint("fk_cold_t3_decisions_operation_authorization", "cold_t3_decisions", type_="foreignkey")
    op.drop_constraint("ck_cold_t3_decisions_recipient_fingerprint", "cold_t3_decisions", type_="check")
    op.alter_column("cold_t3_decisions", "recipient_fingerprint", existing_type=sa.String(64), nullable=False)
    op.create_check_constraint("ck_cold_t3_decisions_recipient_fingerprint", "cold_t3_decisions", "length(recipient_fingerprint)=64")
    op.drop_constraint("uq_cold_delivery_operations_id_authorization", "cold_delivery_operations", type_="unique")
