"""enable pgvector extension

Revision ID: 005_enable_pgvector
Revises: 004_policy_ranking_fields
Create Date: 2026-03-04

"""

from __future__ import annotations

from alembic import op


revision = "005_enable_pgvector"
down_revision = "004_policy_ranking_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
