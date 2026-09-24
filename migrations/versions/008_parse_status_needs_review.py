"""allow parse_status 'needs_review'

Revision ID: 008_parse_status_needs_review
Revises: 007_policy_references
Create Date: 2026-09-24

Phase 3.2 / S5 — structure-aware sectioning. A document that extracts to zero
usable text (a scanned PDF, an image-only DOCX) previously published as READY
with a single empty "main" section, which made an unanswerable policy look
ingested. Such versions now land in `needs_review` so an operator can route them
to OCR, which is distinct from `failed` (the parser itself errored).
"""

from __future__ import annotations

from alembic import op


revision = "008_parse_status_needs_review"
down_revision = "007_policy_references"
branch_labels = None
depends_on = None


_OLD_STATUSES = "'pending','queued','processing','ready','parsed','failed','cancelled','superseded'"
_NEW_STATUSES = f"{_OLD_STATUSES},'needs_review'"


def upgrade() -> None:
    op.execute("ALTER TABLE policy_versions DROP CONSTRAINT IF EXISTS ck_policy_versions_parse_status")
    op.execute(
        f"""
        ALTER TABLE policy_versions
        ADD CONSTRAINT ck_policy_versions_parse_status
        CHECK (parse_status in ({_NEW_STATUSES}))
        """
    )


def downgrade() -> None:
    # Rows already parked in needs_review would violate the narrower constraint;
    # fold them back into 'failed' so the downgrade cannot fail mid-flight.
    op.execute("UPDATE policy_versions SET parse_status = 'failed' WHERE parse_status = 'needs_review'")
    op.execute("ALTER TABLE policy_versions DROP CONSTRAINT IF EXISTS ck_policy_versions_parse_status")
    op.execute(
        f"""
        ALTER TABLE policy_versions
        ADD CONSTRAINT ck_policy_versions_parse_status
        CHECK (parse_status in ({_OLD_STATUSES}))
        """
    )
