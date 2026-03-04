from __future__ import annotations

import uuid
from typing import List

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
