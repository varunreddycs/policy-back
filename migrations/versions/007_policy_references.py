"""add policy_references table

Revision ID: 007_policy_references
Revises: 006_policy_embeddings
Create Date: 2026-04-08

Phase 3.1 — cross-reference extraction. Stores per-section references to other
sections, other policies, or external authorities (statutes/URLs). Resolution is
best-effort and recorded in `resolution_status`. Writes are owned by the worker
post-ingestion hook and the backfill CLI; the API surface is read-only.
"""

from __future__ import annotations

from alembic import op


revision = "007_policy_references"
down_revision = "006_policy_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_references (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,

            source_section_id UUID NOT NULL,
            source_policy_version_id UUID NOT NULL,

            reference_type TEXT NOT NULL,
            resolution_status TEXT NOT NULL,

            target_section_id UUID NULL,
            target_policy_id  UUID NULL,
            target_external_uri   TEXT NULL,
            target_external_label TEXT NULL,

            matched_text TEXT NOT NULL,
            match_offset INTEGER NULL,
            extractor_version TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT fk_policy_references_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
            CONSTRAINT fk_policy_references_source_section_id_policy_sections
                FOREIGN KEY (source_section_id) REFERENCES policy_sections(id) ON DELETE CASCADE,
            CONSTRAINT fk_policy_references_source_policy_version_id_policy_versions
                FOREIGN KEY (source_policy_version_id) REFERENCES policy_versions(id) ON DELETE CASCADE,
            CONSTRAINT fk_policy_references_target_section_id_policy_sections
                FOREIGN KEY (target_section_id) REFERENCES policy_sections(id) ON DELETE SET NULL,
            CONSTRAINT fk_policy_references_target_policy_id_policies
                FOREIGN KEY (target_policy_id) REFERENCES policies(id) ON DELETE SET NULL,
            CONSTRAINT ck_policy_references_reference_type
                CHECK (reference_type IN ('internal_section','cross_policy','external_authority')),
            CONSTRAINT ck_policy_references_resolution_status
                CHECK (resolution_status IN ('resolved','unresolved','external'))
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_tenant_id "
        "ON policy_references (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_source_section_id "
        "ON policy_references (source_section_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_source_policy_version_id "
        "ON policy_references (source_policy_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_target_section_id "
        "ON policy_references (target_section_id) "
        "WHERE target_section_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_target_policy_id "
        "ON policy_references (target_policy_id) "
        "WHERE target_policy_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_policy_references_reference_type "
        "ON policy_references (reference_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_policy_references_reference_type")
    op.execute("DROP INDEX IF EXISTS ix_policy_references_target_policy_id")
    op.execute("DROP INDEX IF EXISTS ix_policy_references_target_section_id")
    op.execute("DROP INDEX IF EXISTS ix_policy_references_source_policy_version_id")
    op.execute("DROP INDEX IF EXISTS ix_policy_references_source_section_id")
    op.execute("DROP INDEX IF EXISTS ix_policy_references_tenant_id")
    op.execute("DROP TABLE IF EXISTS policy_references")
