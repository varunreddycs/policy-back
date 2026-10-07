"""policy_references mapping provenance

Revision ID: 009_reference_mapping_provenance
Revises: 008_parse_status_needs_review
Create Date: 2026-10-06

Phase 3.2 / S3 — framework crosswalks. Adds nullable provenance to
`policy_references` so a curated mapping (e.g. NIST CSF 2.0 -> SP 800-53) can
say where it came from and, when the source states it, how the two sides
relate. Untyped mappings leave `relationship_type` and `strength` NULL; the
extractor-produced rows are unaffected.
"""

from __future__ import annotations

from alembic import op


revision = "009_reference_mapping_provenance"
down_revision = "008_parse_status_needs_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE policy_references
            ADD COLUMN IF NOT EXISTS relationship_type TEXT NULL,
            ADD COLUMN IF NOT EXISTS strength REAL NULL,
            ADD COLUMN IF NOT EXISTS mapping_source TEXT NULL,
            ADD COLUMN IF NOT EXISTS mapping_revision TEXT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE policy_references
        ADD CONSTRAINT ck_policy_references_relationship_type
        CHECK (relationship_type IS NULL OR relationship_type IN
            ('equal','subset_of','superset_of','intersects','not_related'))
        """
    )
    op.execute(
        """
        ALTER TABLE policy_references
        ADD CONSTRAINT ck_policy_references_strength
        CHECK (strength IS NULL OR (strength >= 0 AND strength <= 10))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE policy_references DROP CONSTRAINT IF EXISTS ck_policy_references_strength")
    op.execute("ALTER TABLE policy_references DROP CONSTRAINT IF EXISTS ck_policy_references_relationship_type")
    op.execute(
        """
        ALTER TABLE policy_references
            DROP COLUMN IF EXISTS mapping_revision,
            DROP COLUMN IF EXISTS mapping_source,
            DROP COLUMN IF EXISTS strength,
            DROP COLUMN IF EXISTS relationship_type
        """
    )
