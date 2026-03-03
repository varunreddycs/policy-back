"""add version_label and lineage

Revision ID: 002_version_lineage
Revises: 001_init
Create Date: 2026-02-28

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "002_version_lineage"
down_revision = "001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_versions",
        sa.Column("version_label", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "policy_versions",
        sa.Column("supersedes_policy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_policy_versions_supersedes_policy_version_id_policy_versions",
        "policy_versions",
        "policy_versions",
        ["supersedes_policy_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Optional label unique per policy.
    op.create_index(
        "uq_policy_versions_policy_id_version_label",
        "policy_versions",
        ["policy_id", "version_label"],
        unique=True,
        postgresql_where=sa.text("version_label IS NOT NULL"),
    )

    op.create_index(
        "ix_policy_versions_supersedes_policy_version_id",
        "policy_versions",
        ["supersedes_policy_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_policy_versions_supersedes_policy_version_id", table_name="policy_versions")
    op.drop_index("uq_policy_versions_policy_id_version_label", table_name="policy_versions")
    op.drop_constraint(
        "fk_policy_versions_supersedes_policy_version_id_policy_versions",
        "policy_versions",
        type_="foreignkey",
    )
    op.drop_column("policy_versions", "supersedes_policy_version_id")
    op.drop_column("policy_versions", "version_label")
