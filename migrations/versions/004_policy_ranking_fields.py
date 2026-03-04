"""add policy ranking fields

Revision ID: 004_policy_ranking_fields
Revises: 003_audit_logs
Create Date: 2026-03-02

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "004_policy_ranking_fields"
down_revision = "003_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.add_column(
		"policies",
		sa.Column("authority_level", sa.Integer(), nullable=False, server_default=sa.text("0")),
	)
	op.add_column(
		"policies",
		sa.Column("department_scope", sa.String(length=128), nullable=False, server_default=sa.text("'all'")),
	)
	op.add_column(
		"policies",
		sa.Column("policy_type", sa.String(length=128), nullable=True),
	)

	op.create_index("ix_policies_policy_type", "policies", ["policy_type"], unique=False)
	op.create_index("ix_policies_department_scope", "policies", ["department_scope"], unique=False)
	op.create_index("ix_policies_authority_level", "policies", ["authority_level"], unique=False)

	# Drop server defaults so the ORM defaults remain the source of truth going forward.
	op.alter_column("policies", "authority_level", server_default=None)
	op.alter_column("policies", "department_scope", server_default=None)


def downgrade() -> None:
	op.drop_index("ix_policies_authority_level", table_name="policies")
	op.drop_index("ix_policies_department_scope", table_name="policies")
	op.drop_index("ix_policies_policy_type", table_name="policies")
	op.drop_column("policies", "policy_type")
	op.drop_column("policies", "department_scope")
	op.drop_column("policies", "authority_level")
