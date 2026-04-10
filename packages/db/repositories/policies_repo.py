"""PostgreSQL implementation of IPolicyRepository."""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models.policy_models import Policy
from packages.db.repositories.base import IPolicyRepository
from packages.db.repositories.repo_dtos import PolicyDTO

_SENTINEL = object()


def _policy_to_dto(p: Policy) -> PolicyDTO:
    return PolicyDTO(
        id=p.id,
        tenant_id=p.tenant_id,
        external_id=p.external_id,
        name=p.name,
        status=p.status,
        jurisdiction=p.jurisdiction,
        category=p.category,
        authority_level=p.authority_level,
        department_scope=p.department_scope,
        policy_type=p.policy_type,
        current_version_id=p.current_version_id,
        created_at=p.created_at,
        created_by_user_id=p.created_by_user_id,
        updated_at=p.updated_at,
        updated_by_user_id=p.updated_by_user_id,
    )


class PgPolicyRepository(IPolicyRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, *, policy_id: uuid.UUID) -> Optional[PolicyDTO]:
        p = self._session.get(Policy, policy_id)
        return _policy_to_dto(p) if p else None

    def get_by_external_id(self, *, tenant_id: uuid.UUID, external_id: str) -> Optional[PolicyDTO]:
        stmt = select(Policy).where(Policy.tenant_id == tenant_id, Policy.external_id == external_id)
        p = self._session.execute(stmt).scalars().first()
        return _policy_to_dto(p) if p else None

    def list_for_tenant(self, *, tenant_id: uuid.UUID) -> List[PolicyDTO]:
        stmt = select(Policy).where(Policy.tenant_id == tenant_id).order_by(Policy.created_at.desc())
        return [_policy_to_dto(p) for p in self._session.execute(stmt).scalars().all()]

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        external_id: str,
        name: str,
        status: str = "draft",
        jurisdiction: Optional[str] = None,
        category: Optional[str] = None,
        authority_level: int = 0,
        department_scope: str = "all",
        policy_type: Optional[str] = None,
        created_by_user_id: Optional[uuid.UUID] = None,
    ) -> PolicyDTO:
        p = Policy(
            tenant_id=tenant_id,
            external_id=external_id,
            name=name,
            status=status,
            jurisdiction=jurisdiction,
            category=category,
            authority_level=authority_level,
            department_scope=department_scope,
            policy_type=policy_type,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
        )
        self._session.add(p)
        self._session.flush()
        self._session.refresh(p)
        return _policy_to_dto(p)

    def update(
        self,
        *,
        policy_id: uuid.UUID,
        current_version_id: Optional[uuid.UUID] = _SENTINEL,
        policy_type: Optional[str] = _SENTINEL,
        department_scope: Optional[str] = _SENTINEL,
        authority_level: Optional[int] = _SENTINEL,
        updated_by_user_id: Optional[uuid.UUID] = _SENTINEL,
    ) -> Optional[PolicyDTO]:
        p = self._session.get(Policy, policy_id)
        if p is None:
            return None
        if current_version_id is not _SENTINEL:
            p.current_version_id = current_version_id
        if policy_type is not _SENTINEL:
            p.policy_type = policy_type
        if department_scope is not _SENTINEL:
            p.department_scope = department_scope
        if authority_level is not _SENTINEL:
            p.authority_level = authority_level
        if updated_by_user_id is not _SENTINEL:
            p.updated_by_user_id = updated_by_user_id
        self._session.add(p)
        self._session.flush()
        return _policy_to_dto(p)
