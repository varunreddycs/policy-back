"""Phase 3.1 — backfill cross-references for already-ingested policies.

Usage:
    python tools/backfill_references.py --tenant-id <uuid>
    python tools/backfill_references.py --all-tenants

Walks every policy_version with parse_status='ready', deletes any existing
references for that version (so the script is idempotent), runs the regex
extractor + resolver against each section, and persists the results.

Reads DATABASE_URL from the environment (same as the API/worker).
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import List, Optional

from sqlalchemy import select

from packages.db.models.policy_models import ParseStatus, PolicyVersion
from packages.db.repositories import references_repo
from packages.db.session import get_sessionmaker
from packages.extraction.reference_resolver import extract_and_resolve_for_version


logger = logging.getLogger("backfill_references")


def _setup_logging() -> None:
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s %(message)s",
	)


def _select_versions(session, tenant_id: Optional[uuid.UUID]) -> List[PolicyVersion]:
	stmt = select(PolicyVersion).where(PolicyVersion.parse_status == ParseStatus.READY.value)
	if tenant_id is not None:
		stmt = stmt.where(PolicyVersion.tenant_id == tenant_id)
	stmt = stmt.order_by(PolicyVersion.created_at.asc())
	return list(session.execute(stmt).scalars().all())


def _process_version(session, version: PolicyVersion) -> int:
	references_repo.delete_for_policy_version(session, policy_version_id=version.id)
	rows = extract_and_resolve_for_version(session, policy_version=version)
	references_repo.bulk_insert(session, rows)
	session.commit()
	return len(rows)


def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Backfill policy_references for ready policy versions.")
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument("--tenant-id", type=str, help="Restrict to a single tenant UUID")
	group.add_argument("--all-tenants", action="store_true", help="Process every tenant")
	parser.add_argument("--dry-run", action="store_true", help="Extract + log but do not write")
	args = parser.parse_args(argv)

	_setup_logging()

	tenant_id: Optional[uuid.UUID] = None
	if args.tenant_id:
		try:
			tenant_id = uuid.UUID(args.tenant_id)
		except ValueError:
			logger.error("Invalid --tenant-id: %s", args.tenant_id)
			return 2

	SessionLocal = get_sessionmaker()
	with SessionLocal() as session:
		versions = _select_versions(session, tenant_id)
		logger.info("backfill.start versions=%d", len(versions))

		total_refs = 0
		for v in versions:
			try:
				if args.dry_run:
					rows = extract_and_resolve_for_version(session, policy_version=v)
					session.rollback()
					count = len(rows)
				else:
					count = _process_version(session, v)
				total_refs += count
				logger.info(
					"backfill.version_done policy_version_id=%s tenant_id=%s refs=%d",
					v.id,
					v.tenant_id,
					count,
				)
			except Exception:
				logger.exception(
					"backfill.version_failed policy_version_id=%s",
					v.id,
				)
				session.rollback()

		logger.info("backfill.done versions=%d total_refs=%d dry_run=%s", len(versions), total_refs, args.dry_run)

	return 0


if __name__ == "__main__":
	sys.exit(main())
