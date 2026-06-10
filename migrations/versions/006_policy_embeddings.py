"""add policy_embeddings table

Revision ID: 006_policy_embeddings
Revises: 005_enable_pgvector
Create Date: 2026-03-04

"""

from __future__ import annotations

from alembic import op


revision = "006_policy_embeddings"
down_revision = "005_enable_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_embeddings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            policy_version_id UUID NOT NULL,
            policy_section_id UUID NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding VECTOR(3072) NOT NULL,
            content_sha256 TEXT,
            authority_level INTEGER,
            department_scope TEXT,
            policy_type TEXT,
            effective_date DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_policy_embeddings_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
            CONSTRAINT fk_policy_embeddings_policy_version_id_policy_versions
                FOREIGN KEY (policy_version_id) REFERENCES policy_versions(id) ON DELETE CASCADE,
            CONSTRAINT fk_policy_embeddings_policy_section_id_policy_sections
                FOREIGN KEY (policy_section_id) REFERENCES policy_sections(id) ON DELETE CASCADE,
            CONSTRAINT uq_policy_embeddings_policy_section_id_embedding_model
                UNIQUE (policy_section_id, embedding_model)
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_embeddings_tenant_id ON policy_embeddings (tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_embeddings_policy_version_id ON policy_embeddings (policy_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS policy_embeddings_vector_idx "
        "ON policy_embeddings USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS policy_embeddings_vector_idx")
    op.execute("DROP INDEX IF EXISTS ix_policy_embeddings_policy_version_id")
    op.execute("DROP INDEX IF EXISTS ix_policy_embeddings_tenant_id")
    op.execute("DROP TABLE IF EXISTS policy_embeddings")
