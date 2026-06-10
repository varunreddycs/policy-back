from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from packages.db.repositories.base import (
    IPolicyRepository,
    IPolicySectionRepository,
    IPolicyVersionRepository,
)
from packages.db.repositories.repo_dtos import PolicyDTO, PolicySectionDTO, PolicyVersionDTO, SectionDetailDTO


class PolicyQueryService:
    """Read-only queries for policies and versions.

    Accepts either a RepositorySet (new path) or a raw Session (backward compat).
    """

    def __init__(
        self,
        *,
        repos: Any = None,
        session: Any = None,
    ) -> None:
        if repos is not None:
            self._policies = repos.policies
            self._versions = repos.versions
            self._sections = repos.sections
        elif session is not None:
            # Backward compatibility: build PG repos from session
            from packages.db.repositories.policies_repo import PgPolicyRepository
            from packages.db.repositories.sections_repo import PgPolicySectionRepository
            from packages.db.repositories.versions_repo import PgPolicyVersionRepository

            self._policies = PgPolicyRepository(session)
            self._versions = PgPolicyVersionRepository(session)
            self._sections = PgPolicySectionRepository(session)
        else:
            raise ValueError("PolicyQueryService requires either repos or session")

    def list_policies(self, *, tenant_id: uuid.UUID) -> List[PolicyDTO]:
        return self._policies.list_for_tenant(tenant_id=tenant_id)

    def list_policy_versions(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> List[PolicyVersionDTO]:
        return self._versions.list_for_policy(tenant_id=tenant_id, policy_id=policy_id)

    def list_policy_version_sections(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_version_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> List[PolicySectionDTO]:
        return self._sections.list_for_version(
            tenant_id=tenant_id,
            policy_version_id=policy_version_id,
            limit=limit,
            offset=offset,
        )

    def get_policy_section_detail(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        detail = self._sections.get_detail(tenant_id=tenant_id, section_id=section_id)
        if detail is None:
            return None
        return asdict(detail)
