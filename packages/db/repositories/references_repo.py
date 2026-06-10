"""PostgreSQL implementation of IReferenceRepository.

Also exposes module-level convenience functions for backward compatibility
with existing call-sites (worker, backfill CLI) that pass a raw Session.
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
from packages.db.repositories.base import IReferenceRepository
from packages.db.repositories.repo_dtos import PolicyReferenceDTO


# ---------------------------------------------------------------------------
# ORM → DTO helpers
# ---------------------------------------------------------------------------


def _hydrate_target(session: Session, *, ref: PolicyReference) -> PolicyReferenceDTO:
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

    return PolicyReferenceDTO(
        id=ref.id,
        reference_type=ref.reference_type,
        resolution_status=ref.resolution_status,
        matched_text=ref.matched_text,
        match_offset=ref.match_offset,
        confidence=ref.confidence,
        extractor_version=ref.extractor_version,
        source_section_id=ref.source_section_id,
        source_policy_version_id=ref.source_policy_version_id,
        target_section_id=ref.target_section_id,
        target_policy_id=ref.target_policy_id,
        target_section_title=target_section_title,
        target_section_path=target_section_path,
        target_policy_name=target_policy_name,
        target_external_uri=ref.target_external_uri,
        target_external_label=ref.target_external_label,
        created_at=ref.created_at,
    )


# ---------------------------------------------------------------------------
# Class-based repository (implements interface)
# ---------------------------------------------------------------------------


class PgReferenceRepository(IReferenceRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def bulk_insert(self, refs: List[Dict[str, Any]]) -> int:
        count = 0
        for ref in refs:
            if isinstance(ref, dict):
                self._session.add(PolicyReference(**ref))
            else:
                # Accept ORM instances for backward compat with extract_and_resolve_for_version
                self._session.add(ref)
            count += 1
        return count

    def delete_for_section(self, *, section_id: uuid.UUID) -> int:
        result = self._session.execute(
            delete(PolicyReference).where(PolicyReference.source_section_id == section_id)
        )
        return int(result.rowcount or 0)

    def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
        result = self._session.execute(
            delete(PolicyReference).where(
                PolicyReference.source_policy_version_id == policy_version_id
            )
        )
        return int(result.rowcount or 0)

    def list_outbound_for_section(
        self, *, tenant_id: uuid.UUID, section_id: uuid.UUID
    ) -> List[PolicyReferenceDTO]:
        stmt = (
            select(PolicyReference)
            .where(
                PolicyReference.tenant_id == tenant_id,
                PolicyReference.source_section_id == section_id,
            )
            .order_by(PolicyReference.match_offset.asc().nullsfirst())
        )
        rows = list(self._session.execute(stmt).scalars().all())
        return [_hydrate_target(self._session, ref=r) for r in rows]

    def list_inbound_for_section(
        self, *, tenant_id: uuid.UUID, section_id: uuid.UUID
    ) -> List[PolicyReferenceDTO]:
        stmt = (
            select(PolicyReference)
            .where(
                PolicyReference.tenant_id == tenant_id,
                PolicyReference.target_section_id == section_id,
            )
            .order_by(PolicyReference.created_at.asc())
        )
        rows = list(self._session.execute(stmt).scalars().all())
        return [_hydrate_target(self._session, ref=r) for r in rows]

    def list_for_policy_version(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_version_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[PolicyReferenceDTO]:
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
        rows = list(self._session.execute(stmt).scalars().all())
        return [_hydrate_target(self._session, ref=r) for r in rows]

    def section_exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        row = self._session.execute(
            select(PolicySection.id).where(
                PolicySection.id == section_id, PolicySection.tenant_id == tenant_id
            )
        ).first()
        return row is not None

    def policy_version_exists_for_tenant(
        self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID
    ) -> bool:
        row = self._session.execute(
            select(PolicyVersion.id).where(
                PolicyVersion.id == policy_version_id, PolicyVersion.tenant_id == tenant_id
            )
        ).first()
        return row is not None


# ---------------------------------------------------------------------------
# Module-level convenience functions (backward compatibility)
# ---------------------------------------------------------------------------


def bulk_insert(session: Session, refs: Iterable[PolicyReference]) -> int:
    count = 0
    for ref in refs:
        session.add(ref)
        count += 1
    return count


def delete_for_section(session: Session, *, section_id: uuid.UUID) -> int:
    result = session.execute(
        delete(PolicyReference).where(PolicyReference.source_section_id == section_id)
    )
    return int(result.rowcount or 0)


def delete_for_policy_version(session: Session, *, policy_version_id: uuid.UUID) -> int:
    result = session.execute(
        delete(PolicyReference).where(
            PolicyReference.source_policy_version_id == policy_version_id
        )
    )
    return int(result.rowcount or 0)


def list_outbound_for_section(
    session: Session, *, tenant_id: uuid.UUID, section_id: uuid.UUID
) -> List[Dict[str, Any]]:
    repo = PgReferenceRepository(session)
    dtos = repo.list_outbound_for_section(tenant_id=tenant_id, section_id=section_id)
    return [_dto_to_dict(d) for d in dtos]


def list_inbound_for_section(
    session: Session, *, tenant_id: uuid.UUID, section_id: uuid.UUID
) -> List[Dict[str, Any]]:
    repo = PgReferenceRepository(session)
    dtos = repo.list_inbound_for_section(tenant_id=tenant_id, section_id=section_id)
    return [_dto_to_dict(d) for d in dtos]


def list_for_policy_version(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    policy_version_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    repo = PgReferenceRepository(session)
    dtos = repo.list_for_policy_version(
        tenant_id=tenant_id, policy_version_id=policy_version_id, limit=limit, offset=offset
    )
    return [_dto_to_dict(d) for d in dtos]


def section_exists_for_tenant(
    session: Session, *, tenant_id: uuid.UUID, section_id: uuid.UUID
) -> bool:
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


def _dto_to_dict(d: PolicyReferenceDTO) -> Dict[str, Any]:
    """Convert DTO back to dict for backward compat with existing API router responses."""
    return {
        "id": d.id,
        "reference_type": d.reference_type,
        "resolution_status": d.resolution_status,
        "matched_text": d.matched_text,
        "match_offset": d.match_offset,
        "confidence": d.confidence,
        "extractor_version": d.extractor_version,
        "source_section_id": d.source_section_id,
        "source_policy_version_id": d.source_policy_version_id,
        "target_section_id": d.target_section_id,
        "target_policy_id": d.target_policy_id,
        "target_section_title": d.target_section_title,
        "target_section_path": d.target_section_path,
        "target_policy_name": d.target_policy_name,
        "target_external_uri": d.target_external_uri,
        "target_external_label": d.target_external_label,
        "created_at": d.created_at,
    }
