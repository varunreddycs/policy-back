"""Phase 3.1 — data access for `policy_references`.

Module-level functions over a Session, matching the lightweight style of
`packages/db/policy_query_service.py`. Writes are owned by the worker hook
and the backfill CLI; reads are used by the API router.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.db.models.policy_models import (
	Policy,
	PolicyReference,
	PolicySection,
	PolicyVersion,
)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def bulk_insert(session: Session, refs: Iterable[PolicyReference]) -> int:
	"""Add the given references to the session. Caller commits."""
	count = 0
	for ref in refs:
		session.add(ref)
		count += 1
	return count


def delete_for_section(session: Session, *, section_id: uuid.UUID) -> int:
	"""Delete all references where this section is the *source*. Caller commits."""
	result = session.execute(
		delete(PolicyReference).where(PolicyReference.source_section_id == section_id)
	)
	return int(result.rowcount or 0)


def delete_for_policy_version(session: Session, *, policy_version_id: uuid.UUID) -> int:
	"""Delete all references whose source belongs to this policy version. Caller commits."""
	result = session.execute(
		delete(PolicyReference).where(
			PolicyReference.source_policy_version_id == policy_version_id
		)
	)
	return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _hydrate_target(session: Session, *, ref: PolicyReference) -> Dict[str, Any]:
	"""Look up target section title + policy name when present.

	Kept simple (one query per ref). The expected fan-out per section is
	small (typically <20 refs), and these endpoints are not on a hot path.
	"""
	target_section_title: Optional[str] = None
	target_section_path: Optional[str] = None
	target_policy_name: Optional[str] = None

	if ref.target_section_id is not None:
		row = session.execute(
			select(PolicySection.title, PolicySection.section_path).where(
				PolicySection.id == ref.target_section_id
			)
		).first()
		if row:
			target_section_title, target_section_path = row

	if ref.target_policy_id is not None:
		name = session.execute(
			select(Policy.name).where(Policy.id == ref.target_policy_id)
		).scalar_one_or_none()
		if name:
			target_policy_name = name

	return {
		"id": ref.id,
		"reference_type": ref.reference_type,
		"resolution_status": ref.resolution_status,
		"matched_text": ref.matched_text,
		"match_offset": ref.match_offset,
		"confidence": ref.confidence,
		"extractor_version": ref.extractor_version,
		"source_section_id": ref.source_section_id,
		"source_policy_version_id": ref.source_policy_version_id,
		"target_section_id": ref.target_section_id,
		"target_policy_id": ref.target_policy_id,
		"target_section_title": target_section_title,
		"target_section_path": target_section_path,
		"target_policy_name": target_policy_name,
		"target_external_uri": ref.target_external_uri,
		"target_external_label": ref.target_external_label,
		"created_at": ref.created_at,
	}


def list_outbound_for_section(
	session: Session,
	*,
	tenant_id: uuid.UUID,
	section_id: uuid.UUID,
) -> List[Dict[str, Any]]:
	stmt = (
		select(PolicyReference)
		.where(
			PolicyReference.tenant_id == tenant_id,
			PolicyReference.source_section_id == section_id,
		)
		.order_by(PolicyReference.match_offset.asc().nullsfirst())
	)
	rows = list(session.execute(stmt).scalars().all())
	return [_hydrate_target(session, ref=r) for r in rows]


def list_inbound_for_section(
	session: Session,
	*,
	tenant_id: uuid.UUID,
	section_id: uuid.UUID,
) -> List[Dict[str, Any]]:
	stmt = (
		select(PolicyReference)
		.where(
			PolicyReference.tenant_id == tenant_id,
			PolicyReference.target_section_id == section_id,
		)
		.order_by(PolicyReference.created_at.asc())
	)
	rows = list(session.execute(stmt).scalars().all())
	return [_hydrate_target(session, ref=r) for r in rows]


def list_for_policy_version(
	session: Session,
	*,
	tenant_id: uuid.UUID,
	policy_version_id: uuid.UUID,
	limit: int = 50,
	offset: int = 0,
) -> List[Dict[str, Any]]:
	limit = max(1, min(int(limit), 200))
	offset = max(0, int(offset))

	stmt = (
		select(PolicyReference)
		.where(
			PolicyReference.tenant_id == tenant_id,
			PolicyReference.source_policy_version_id == policy_version_id,
		)
		.order_by(PolicyReference.created_at.asc())
		.limit(limit)
		.offset(offset)
	)
	rows = list(session.execute(stmt).scalars().all())
	return [_hydrate_target(session, ref=r) for r in rows]


def section_exists_for_tenant(
	session: Session, *, tenant_id: uuid.UUID, section_id: uuid.UUID
) -> bool:
	"""Used by the API router to return 404 vs empty list."""
	row = session.execute(
		select(PolicySection.id).where(
			PolicySection.id == section_id, PolicySection.tenant_id == tenant_id
		)
	).first()
	return row is not None


def policy_version_exists_for_tenant(
	session: Session, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID
) -> bool:
	row = session.execute(
		select(PolicyVersion.id).where(
			PolicyVersion.id == policy_version_id, PolicyVersion.tenant_id == tenant_id
		)
	).first()
	return row is not None
