"""PostgreSQL implementation of IPolicySectionRepository."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.db.models.policy_models import Policy, PolicySection, PolicyVersion
from packages.db.repositories.base import IPolicySectionRepository
from packages.db.repositories.repo_dtos import PolicySectionDTO, SectionDetailDTO


def _section_to_dto(s: PolicySection) -> PolicySectionDTO:
    return PolicySectionDTO(
        id=s.id,
        tenant_id=s.tenant_id,
        policy_version_id=s.policy_version_id,
        section_index=s.section_index,
        section_path=s.section_path,
        title=s.title,
        text=s.text,
        start_offset=s.start_offset,
        end_offset=s.end_offset,
        content_sha256=s.content_sha256,
        rag_document_id=s.rag_document_id,
        rag_node_id=s.rag_node_id,
        created_at=s.created_at,
    )


class PgPolicySectionRepository(IPolicySectionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_version(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_version_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> List[PolicySectionDTO]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        stmt = (
            select(PolicySection)
            .where(
                PolicySection.tenant_id == tenant_id,
                PolicySection.policy_version_id == policy_version_id,
            )
            .order_by(PolicySection.section_index.asc())
            .limit(limit)
            .offset(offset)
        )
        return [_section_to_dto(s) for s in self._session.execute(stmt).scalars().all()]

    def get_detail(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> Optional[SectionDetailDTO]:
        stmt = (
            select(PolicySection, PolicyVersion, Policy)
            .join(PolicyVersion, PolicyVersion.id == PolicySection.policy_version_id)
            .join(Policy, Policy.id == PolicyVersion.policy_id)
            .where(
                PolicySection.tenant_id == tenant_id,
                PolicySection.id == section_id,
            )
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None

        section, version, policy = row
        metadata = dict(version.metadata_json or {})
        public_url = metadata.get("source_url") or metadata.get("public_url") or metadata.get("url")
        return SectionDetailDTO(
            section_id=section.id,
            tenant_id=section.tenant_id,
            policy_id=policy.id,
            policy_version_id=version.id,
            policy_name=policy.name,
            section_index=section.section_index,
            section_path=section.section_path,
            section_title=section.title,
            text=section.text,
            effective_date=version.effective_date,
            is_current=bool(version.is_current),
            public_url=public_url,
            metadata=metadata,
        )

    def bulk_insert(self, sections: List[Dict[str, Any]]) -> int:
        count = 0
        for s in sections:
            self._session.add(PolicySection(**s))
            count += 1
        self._session.flush()
        return count

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        result = self._session.execute(
            delete(PolicySection).where(PolicySection.policy_version_id == policy_version_id)
        )
        return int(result.rowcount or 0)

    def exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        row = self._session.execute(
            select(PolicySection.id).where(
                PolicySection.id == section_id, PolicySection.tenant_id == tenant_id
            )
        ).first()
        return row is not None
