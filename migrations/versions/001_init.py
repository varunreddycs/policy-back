"""init schema for policy versioning

Revision ID: 001_init
Revises: 
Create Date: 2026-02-27

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
	# PostgreSQL UUID default helper (requires pgcrypto)
	op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

	op.create_table(
		"tenants",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column("slug", sa.String(length=128), nullable=False),
		sa.Column("name", sa.String(length=256), nullable=False),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.UniqueConstraint("slug", name="uq_tenants_slug"),
	)
	op.create_index("ix_tenants_is_active", "tenants", ["is_active"], unique=False)

	op.create_table(
		"users",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column("email", sa.String(length=320), nullable=False),
		sa.Column("display_name", sa.String(length=256), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
	)
	op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
	op.create_index("ix_users_is_active", "users", ["is_active"], unique=False)

	op.create_table(
		"ingest_batches",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"submitted_by_user_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("users.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("source_system", sa.String(length=128), nullable=True),
		sa.Column("correlation_id", sa.String(length=128), nullable=True),
		sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'received'")),
		sa.Column("status_reason", sa.Text(), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.CheckConstraint(
			"status in ('received','queued','processing','completed','failed')",
			name="ck_ingest_batches_status",
		),
	)
	op.create_index("ix_ingest_batches_tenant_id", "ingest_batches", ["tenant_id"], unique=False)
	op.create_index("ix_ingest_batches_status", "ingest_batches", ["status"], unique=False)
	op.create_index("ix_ingest_batches_created_at", "ingest_batches", ["created_at"], unique=False)

	op.create_table(
		"policies",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column("external_id", sa.String(length=128), nullable=False),
		sa.Column("name", sa.String(length=512), nullable=False),
		sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")),
		sa.Column("jurisdiction", sa.String(length=128), nullable=True),
		sa.Column("category", sa.String(length=256), nullable=True),
		# current version pointer set after policy_versions exists
		sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
		sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
		sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.UniqueConstraint("tenant_id", "external_id", name="uq_policies_tenant_id_external_id"),
		sa.CheckConstraint("status in ('draft','active','retired')", name="ck_policies_status"),
		sa.ForeignKeyConstraint(
			["created_by_user_id"],
			["users.id"],
			name="fk_policies_created_by_user_id_users",
			ondelete="SET NULL",
		),
		sa.ForeignKeyConstraint(
			["updated_by_user_id"],
			["users.id"],
			name="fk_policies_updated_by_user_id_users",
			ondelete="SET NULL",
		),
	)
	op.create_index("ix_policies_tenant_id", "policies", ["tenant_id"], unique=False)
	op.create_index("ix_policies_status", "policies", ["status"], unique=False)

	op.create_table(
		"policy_versions",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"policy_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("policies.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column("version_number", sa.Integer(), nullable=False),
		sa.Column("title", sa.String(length=512), nullable=True),
		sa.Column("effective_date", sa.Date(), nullable=True),
		sa.Column("blob_container", sa.String(length=128), nullable=False),
		sa.Column("blob_name", sa.String(length=1024), nullable=False),
		sa.Column("blob_version_id", sa.String(length=256), nullable=True),
		sa.Column("blob_etag", sa.String(length=128), nullable=True),
		sa.Column("content_type", sa.String(length=128), nullable=True),
		sa.Column("content_length", sa.Integer(), nullable=True),
		sa.Column("extracted_blob_container", sa.String(length=128), nullable=True),
		sa.Column("extracted_blob_name", sa.String(length=1024), nullable=True),
		sa.Column("extracted_blob_uri", sa.Text(), nullable=True),
		sa.Column("content_sha256", sa.String(length=64), nullable=False),
		sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
		sa.Column("metadata_sha256", sa.String(length=64), nullable=False),
		sa.Column(
			"ingest_batch_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("ingest_batches.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("parse_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
		sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("parse_status_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("parse_error_code", sa.String(length=128), nullable=True),
		sa.Column("parse_error_message", sa.Text(), nullable=True),
		sa.Column("correlation_id", sa.String(length=128), nullable=True),
		sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.CheckConstraint("version_number >= 1", name="ck_policy_versions_version_number_gte_1"),
		sa.CheckConstraint(
			"parse_status in ('pending','queued','processing','ready','parsed','failed','cancelled','superseded')",
			name="ck_policy_versions_parse_status",
		),
		sa.ForeignKeyConstraint(
			["created_by_user_id"],
			["users.id"],
			name="fk_policy_versions_created_by_user_id_users",
			ondelete="SET NULL",
		),
		sa.UniqueConstraint("policy_id", "version_number", name="uq_policy_versions_policy_id_version_number"),
		sa.UniqueConstraint(
			"policy_id",
			"content_sha256",
			"metadata_sha256",
			name="uq_policy_versions_policy_id_content_sha256_metadata_sha256",
		),
	)
	op.create_index("ix_policy_versions_tenant_id", "policy_versions", ["tenant_id"], unique=False)
	op.create_index("ix_policy_versions_policy_id", "policy_versions", ["policy_id"], unique=False)
	op.create_index("ix_policy_versions_created_at", "policy_versions", ["created_at"], unique=False)
	op.create_index("ix_policy_versions_parse_status", "policy_versions", ["parse_status"], unique=False)
	op.create_index("ix_policy_versions_content_sha256", "policy_versions", ["content_sha256"], unique=False)
	op.create_index("ix_policy_versions_is_current", "policy_versions", ["is_current"], unique=False)
	op.create_index(
		"uq_policy_versions_one_current_per_policy",
		"policy_versions",
		["policy_id"],
		unique=True,
		postgresql_where=sa.text("is_current"),
	)

	# Add the current version foreign key after policy_versions exists.
	op.create_foreign_key(
		"fk_policies_current_version_id_policy_versions",
		source_table="policies",
		referent_table="policy_versions",
		local_cols=["current_version_id"],
		remote_cols=["id"],
		ondelete="SET NULL",
	)
	op.create_index("ix_policies_current_version_id", "policies", ["current_version_id"], unique=False)

	op.create_table(
		"policy_sections",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"policy_version_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("policy_versions.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column("section_index", sa.Integer(), nullable=False),
		sa.Column("section_path", sa.String(length=1024), nullable=True),
		sa.Column("title", sa.String(length=512), nullable=True),
		sa.Column("text", sa.Text(), nullable=False),
		sa.Column("start_offset", sa.Integer(), nullable=True),
		sa.Column("end_offset", sa.Integer(), nullable=True),
		sa.Column("content_sha256", sa.String(length=64), nullable=False),
		sa.Column("rag_document_id", sa.String(length=256), nullable=True),
		sa.Column("rag_node_id", sa.String(length=256), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.CheckConstraint("section_index >= 0", name="ck_policy_sections_section_index_gte_0"),
		sa.UniqueConstraint(
			"policy_version_id",
			"section_index",
			name="uq_policy_sections_policy_version_id_section_index",
		),
	)
	op.create_index("ix_policy_sections_tenant_id", "policy_sections", ["tenant_id"], unique=False)
	op.create_index("ix_policy_sections_policy_version_id", "policy_sections", ["policy_version_id"], unique=False)
	op.create_index("ix_policy_sections_content_sha256", "policy_sections", ["content_sha256"], unique=False)

	op.create_table(
		"ingest_items",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
			server_default=sa.text("gen_random_uuid()"),
		),
		sa.Column(
			"tenant_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"batch_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("ingest_batches.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"policy_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("policies.id", ondelete="SET NULL"),
			nullable=True,
		),
		# blob pointers for the raw input document
		sa.Column("blob_container", sa.String(length=128), nullable=False),
		sa.Column("blob_name", sa.String(length=1024), nullable=False),
		sa.Column("blob_version_id", sa.String(length=256), nullable=True),
		sa.Column("blob_etag", sa.String(length=128), nullable=True),
		sa.Column("content_type", sa.String(length=128), nullable=True),
		sa.Column("content_length", sa.Integer(), nullable=True),
		sa.Column("content_sha256", sa.String(length=64), nullable=True),
		sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
		sa.Column("metadata_sha256", sa.String(length=64), nullable=True),
		sa.Column("correlation_id", sa.String(length=128), nullable=True),
		sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'received'")),
		sa.Column("error_code", sa.String(length=128), nullable=True),
		sa.Column("error_message", sa.Text(), nullable=True),
		sa.Column(
			"result_policy_version_id",
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey("policy_versions.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.CheckConstraint(
			"status in ('received','queued','processing','completed','failed')",
			name="ck_ingest_items_status",
		),
	)
	op.create_index("ix_ingest_items_tenant_id", "ingest_items", ["tenant_id"], unique=False)
	op.create_index("ix_ingest_items_batch_id", "ingest_items", ["batch_id"], unique=False)
	op.create_index("ix_ingest_items_policy_id", "ingest_items", ["policy_id"], unique=False)
	op.create_index("ix_ingest_items_status", "ingest_items", ["status"], unique=False)
	op.create_index("ix_ingest_items_content_sha256", "ingest_items", ["content_sha256"], unique=False)


def downgrade() -> None:
	# Drop in reverse dependency order.
	op.drop_index("ix_ingest_items_content_sha256", table_name="ingest_items")
	op.drop_index("ix_ingest_items_status", table_name="ingest_items")
	op.drop_index("ix_ingest_items_policy_id", table_name="ingest_items")
	op.drop_index("ix_ingest_items_batch_id", table_name="ingest_items")
	op.drop_index("ix_ingest_items_tenant_id", table_name="ingest_items")
	op.drop_table("ingest_items")

	op.drop_index("ix_policy_sections_content_sha256", table_name="policy_sections")
	op.drop_index("ix_policy_sections_policy_version_id", table_name="policy_sections")
	op.drop_index("ix_policy_sections_tenant_id", table_name="policy_sections")
	op.drop_table("policy_sections")

	op.drop_index("ix_policies_current_version_id", table_name="policies")
	op.drop_constraint(
		"fk_policies_current_version_id_policy_versions",
		"policies",
		type_="foreignkey",
	)

	op.drop_index("uq_policy_versions_one_current_per_policy", table_name="policy_versions")
	op.drop_index("ix_policy_versions_is_current", table_name="policy_versions")
	op.drop_index("ix_policy_versions_content_sha256", table_name="policy_versions")
	op.drop_index("ix_policy_versions_parse_status", table_name="policy_versions")
	op.drop_index("ix_policy_versions_created_at", table_name="policy_versions")
	op.drop_index("ix_policy_versions_policy_id", table_name="policy_versions")
	op.drop_index("ix_policy_versions_tenant_id", table_name="policy_versions")
	op.drop_table("policy_versions")

	op.drop_index("ix_policies_status", table_name="policies")
	op.drop_index("ix_policies_tenant_id", table_name="policies")
	op.drop_table("policies")

	op.drop_index("ix_ingest_batches_created_at", table_name="ingest_batches")
	op.drop_index("ix_ingest_batches_status", table_name="ingest_batches")
	op.drop_index("ix_ingest_batches_tenant_id", table_name="ingest_batches")
	op.drop_table("ingest_batches")

	op.drop_index("ix_users_is_active", table_name="users")
	op.drop_index("ix_users_tenant_id", table_name="users")
	op.drop_table("users")

	op.drop_index("ix_tenants_is_active", table_name="tenants")
	op.drop_table("tenants")

	# Leave pgcrypto extension in place; it may be shared.
