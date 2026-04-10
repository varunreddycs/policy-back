"""Phase 3.1 — backfill cross-references for already-ingested policy sections.

Finds policy versions whose sections have no reference rows yet (via LEFT JOIN
WHERE NULL), then runs the same extraction + resolution pipeline that the worker
normally kicks off post-ingestion. Idempotent: the worker's delete-then-insert
strategy means re-running on the same version simply regenerates the same rows.

Usage:
    python -m apps.worker.jobs.ref_backfill --tenant-id <UUID>
    python -m apps.worker.jobs.ref_backfill --tenant-id <UUID> --batch-size 50
    python -m apps.worker.jobs.ref_backfill --tenant-id <UUID> --all-tenants
"""

from __future__ import annotations

import argparse
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from packages.db.models.policy_models import ParseStatus, Policy, PolicySection, PolicyVersion
from packages.db.repositories import references_repo
from packages.db.session import get_sessionmaker
from packages.extraction.reference_resolver import extract_and_resolve_for_version


logger = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    versions_scanned: int = 0
    versions_processed: int = 0
    references_inserted: int = 0


def _fetch_unprocessed_version_ids(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    limit: int,
) -> list[uuid.UUID]:
    """Return IDs of READY versions that have ≥1 section with no reference rows yet."""
    # Subquery: version IDs that already have at least one reference row.
    from packages.db.models.policy_models import PolicyReference

    processed_subq = (
        select(PolicyVersion.id)
        .join(PolicySection, PolicySection.policy_version_id == PolicyVersion.id)
        .join(PolicyReference, PolicyReference.source_section_id == PolicySection.id)
        .where(PolicyVersion.tenant_id == tenant_id)
        .distinct()
        .scalar_subquery()
    )

    stmt = (
        select(PolicyVersion.id)
        .where(
            PolicyVersion.tenant_id == tenant_id,
            PolicyVersion.parse_status == ParseStatus.READY.value,
            PolicyVersion.id.not_in(processed_subq),
        )
        .order_by(PolicyVersion.created_at.asc())
        .limit(limit)
    )
    return [row[0] for row in session.execute(stmt).all()]


def _process_version(session: Session, version_id: uuid.UUID) -> int:
    """Extract + resolve + persist references for one policy version.

    Returns the number of reference rows inserted.
    Raises on unrecoverable errors; caller handles rollback.
    """
    version = session.execute(
        select(PolicyVersion)
        .where(PolicyVersion.id == version_id)
        .options(selectinload(PolicyVersion.sections))
    ).scalar_one_or_none()

    if version is None:
        logger.warning("ref_backfill.version_not_found", extra={"policy_version_id": str(version_id)})
        return 0

    references_repo.delete_for_policy_version(session, policy_version_id=version.id)
    ref_rows = extract_and_resolve_for_version(session, policy_version=version)
    count = references_repo.bulk_insert(session, ref_rows)
    return count


def backfill_references(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    batch_size: int = 50,
) -> BackfillStats:
    """Run reference backfill for one tenant until all READY versions are processed."""
    stats = BackfillStats()

    while True:
        version_ids = _fetch_unprocessed_version_ids(
            session=session,
            tenant_id=tenant_id,
            limit=batch_size,
        )
        if not version_ids:
            return stats

        for version_id in version_ids:
            stats.versions_scanned += 1
            try:
                count = _process_version(session, version_id)
                session.commit()
                stats.versions_processed += 1
                stats.references_inserted += count
                logger.info(
                    "ref_backfill.version_done",
                    extra={
                        "policy_version_id": str(version_id),
                        "references_inserted": count,
                    },
                )
            except Exception:
                logger.exception(
                    "ref_backfill.version_failed",
                    extra={"policy_version_id": str(version_id)},
                )
                try:
                    session.rollback()
                except Exception:
                    pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill policy section cross-references")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID to backfill")
    parser.add_argument("--batch-size", type=int, default=50, help="Policy versions per batch")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args()
    tenant_id = uuid.UUID(args.tenant_id)
    SessionLocal = get_sessionmaker()

    with SessionLocal() as session:
        stats = backfill_references(
            session=session,
            tenant_id=tenant_id,
            batch_size=max(1, int(args.batch_size)),
        )

    print(
        {
            "tenant_id": str(tenant_id),
            "versions_scanned": stats.versions_scanned,
            "versions_processed": stats.versions_processed,
            "references_inserted": stats.references_inserted,
        }
    )


if __name__ == "__main__":
    main()
