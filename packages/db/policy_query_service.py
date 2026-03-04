from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models.policy_models import Policy, PolicySection, PolicyVersion


class PolicyQueryService:
	"""Read-only queries for policies and versions."""

	def __init__(self, *, session: Session) -> None:
		self._session = session

	def list_policies(self, *, tenant_id: uuid.UUID) -> List[Policy]:
		stmt = select(Policy).where(Policy.tenant_id == tenant_id).order_by(Policy.created_at.desc())
		return list(self._session.execute(stmt).scalars().all())

	def list_policy_versions(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> List[PolicyVersion]:
		stmt = (
			select(PolicyVersion)
			.where(PolicyVersion.tenant_id == tenant_id, PolicyVersion.policy_id == policy_id)
			.order_by(PolicyVersion.version_number.desc())
		)
		return list(self._session.execute(stmt).scalars().all())

	def list_policy_version_sections(
		self,
		*,
		tenant_id: uuid.UUID,
		policy_version_id: uuid.UUID,
		limit: int = 20,
		offset: int = 0,
	) -> List[PolicySection]:
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
		return list(self._session.execute(stmt).scalars().all())

	def get_policy_section_detail(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> Optional[Dict[str, Any]]:
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
		return {
			"section_id": section.id,
			"tenant_id": section.tenant_id,
			"policy_id": policy.id,
			"policy_version_id": version.id,
			"policy_name": policy.name,
			"section_index": section.section_index,
			"section_path": section.section_path,
			"section_title": section.title,
			"text": section.text,
			"effective_date": version.effective_date,
			"is_current": bool(version.is_current),
			"public_url": public_url,
			"metadata": metadata,
		}
