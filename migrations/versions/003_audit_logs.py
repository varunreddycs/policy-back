"""add audit_logs table

Revision ID: 003_audit_logs
Revises: 002_version_lineage
Create Date: 2026-03-02

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "003_audit_logs"
down_revision = "002_version_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"audit_logs",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column("correlation_id", sa.String(length=128), nullable=True),
		sa.Column("event_type", sa.String(length=64), nullable=False),
		sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
	)
	op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"], unique=False)
	op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
	op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)


def downgrade() -> None:
	op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
	op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
	op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
	op.drop_table("audit_logs")
