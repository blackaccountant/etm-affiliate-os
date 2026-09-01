"""add B4A durable cold dispatch reservation

Revision ID: e1f2a3b4c5d6
Revises: e0f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("cold_dispatch_reservations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("cold_delivery_operations.id"), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False), sa.Column("provider_contract_version", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False), sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("execution_fence_identity", sa.String(255), nullable=False), sa.Column("expected_state_revision", sa.Integer(), nullable=False),
        sa.Column("recipient_fingerprint", sa.String(64), nullable=False), sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("sender_fingerprint", sa.String(64), nullable=False), sa.Column("provider_payload_fingerprint", sa.String(64), nullable=False), sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operation_id", name="uq_cold_dispatch_reservations_operation"), sa.UniqueConstraint("reservation_id", name="uq_cold_dispatch_reservations_id"),
        *[sa.CheckConstraint(f"length({column}) = 64", name=name) for column, name in (("idempotency_key", "ck_cold_dispatch_reservations_idempotency"), ("recipient_fingerprint", "ck_cold_dispatch_reservations_recipient"), ("content_fingerprint", "ck_cold_dispatch_reservations_content"), ("sender_fingerprint", "ck_cold_dispatch_reservations_sender"), ("provider_payload_fingerprint", "ck_cold_dispatch_reservations_payload"))])
    op.drop_constraint("ck_cold_delivery_operation_state_value", "cold_delivery_operation_state", type_="check")
    op.create_check_constraint("ck_cold_delivery_operation_state_value", "cold_delivery_operation_state", "current_state IN ('CREATED','READY','T3_BLOCKED','DISPATCH_PLANNED','PRE_SEND_BLOCKED','DISPATCHING','ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_cold_delivery_operation_state_transition ON cold_delivery_operation_state")
        op.execute("CREATE TRIGGER trg_cold_delivery_operation_state_transition BEFORE UPDATE ON cold_delivery_operation_state FOR EACH ROW EXECUTE FUNCTION enforce_cold_delivery_state_transition()")
        op.execute("""CREATE OR REPLACE FUNCTION enforce_cold_delivery_state_transition() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.current_state <> OLD.current_state AND NOT ((OLD.current_state='CREATED' AND NEW.current_state IN ('READY','T3_BLOCKED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='READY' AND NEW.current_state IN ('DISPATCH_PLANNED','T3_BLOCKED','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='DISPATCH_PLANNED' AND NEW.current_state IN ('PRE_SEND_BLOCKED','DISPATCHING','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='DISPATCHING' AND NEW.current_state IN ('ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='TECHNICAL_RETRY_DUE' AND NEW.current_state IN ('DISPATCH_PLANNED','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='RECONCILIATION_REQUIRED' AND NEW.current_state IN ('ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','UNRESOLVED_TERMINAL'))) THEN RAISE EXCEPTION 'invalid cold delivery state transition'; END IF; RETURN NEW; END; $$""")

def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_cold_delivery_operation_state_transition ON cold_delivery_operation_state")
        op.execute("""CREATE OR REPLACE FUNCTION enforce_cold_delivery_state_transition() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.current_state <> OLD.current_state AND NOT ((OLD.current_state='CREATED' AND NEW.current_state IN ('READY','T3_BLOCKED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='READY' AND NEW.current_state IN ('DISPATCH_PLANNED','T3_BLOCKED','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='DISPATCH_PLANNED' AND NEW.current_state IN ('DISPATCHING','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='DISPATCHING' AND NEW.current_state IN ('ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='TECHNICAL_RETRY_DUE' AND NEW.current_state IN ('DISPATCH_PLANNED','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')) OR (OLD.current_state='RECONCILIATION_REQUIRED' AND NEW.current_state IN ('ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','UNRESOLVED_TERMINAL'))) THEN RAISE EXCEPTION 'invalid cold delivery state transition'; END IF; RETURN NEW; END; $$""")
        op.execute("CREATE TRIGGER trg_cold_delivery_operation_state_transition BEFORE UPDATE ON cold_delivery_operation_state FOR EACH ROW EXECUTE FUNCTION enforce_cold_delivery_state_transition()")
    op.drop_constraint("ck_cold_delivery_operation_state_value", "cold_delivery_operation_state", type_="check")
    op.create_check_constraint("ck_cold_delivery_operation_state_value", "cold_delivery_operation_state", "current_state IN ('CREATED','READY','T3_BLOCKED','DISPATCH_PLANNED','DISPATCHING','ACCEPTED','REJECTED','TECHNICAL_RETRY_DUE','RECONCILIATION_REQUIRED','UNRESOLVED_TERMINAL')")
    op.drop_table("cold_dispatch_reservations")
