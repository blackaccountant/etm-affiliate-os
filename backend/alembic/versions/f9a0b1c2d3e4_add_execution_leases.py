"""add durable execution lease authority"""
from alembic import op
import sqlalchemy as sa
revision="f9a0b1c2d3e4"
down_revision="f8a9b0c1d2e3"
branch_labels=None
depends_on=None
def upgrade():
 op.add_column("executions",sa.Column("lease_owner",sa.String(64),nullable=True))
 op.add_column("executions",sa.Column("lease_generation",sa.Integer(),nullable=False,server_default="0"))
 op.add_column("executions",sa.Column("lease_expires_at",sa.DateTime(timezone=True),nullable=True))
 op.create_index("ix_executions_lease_owner","executions",["lease_owner"])
 op.create_index("ix_executions_lease_expires_at","executions",["lease_expires_at"])
def downgrade():
 op.drop_index("ix_executions_lease_expires_at",table_name="executions")
 op.drop_index("ix_executions_lease_owner",table_name="executions")
 op.drop_column("executions","lease_expires_at")
 op.drop_column("executions","lease_generation")
 op.drop_column("executions","lease_owner")
