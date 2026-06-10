from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.db.models.policy_models import IngestBatch, IngestItem, Policy, PolicyVersion


class RepositoryError(RuntimeError):
	pass


class PolicyRepository:
	def __init__(self, session: Session) -> None:
		self._session = session

	def get_by_external_id(self, *, tenant_id: uuid.UUID, external_id: str) -> Optional[Policy]:
		stmt = select(Policy).where(Policy.tenant_id == tenant_id, Policy.external_id == external_id)
		return self._session.execute(stmt).scalars().first()

	def add(self, policy: Policy) -> Policy:
		self._session.add(policy)
		return policy


class PolicyVersionRepository:
	def __init__(self, session: Session) -> None:
		self._session = session

	def exists_duplicate(
		self,
		*,
		policy_id: uuid.UUID,
		content_sha256: str,
		metadata_sha256: str,
	) -> Optional[uuid.UUID]:
		stmt = (
			select(PolicyVersion.id)
			.where(
				PolicyVersion.policy_id == policy_id,
				PolicyVersion.content_sha256 == content_sha256,
				PolicyVersion.metadata_sha256 == metadata_sha256,
			)
			.limit(1)
		)
		return self._session.execute(stmt).scalars().first()

	def next_version_number(self, *, policy_id: uuid.UUID) -> int:
		stmt = select(func.coalesce(func.max(PolicyVersion.version_number), 0) + 1).where(
			PolicyVersion.policy_id == policy_id
		)
		return int(self._session.execute(stmt).scalar_one())

	def latest_version_id(self, *, policy_id: uuid.UUID) -> Optional[uuid.UUID]:
		stmt = (
			select(PolicyVersion.id)
			.where(PolicyVersion.policy_id == policy_id)
			.order_by(PolicyVersion.version_number.desc())
			.limit(1)
		)
		return self._session.execute(stmt).scalars().first()

	def add(self, policy_version: PolicyVersion) -> PolicyVersion:
		self._session.add(policy_version)
		return policy_version


class IngestBatchRepository:
	def __init__(self, session: Session) -> None:
		self._session = session

	def get(self, batch_id: uuid.UUID) -> Optional[IngestBatch]:
		return self._session.get(IngestBatch, batch_id)

	def add(self, batch: IngestBatch) -> IngestBatch:
		self._session.add(batch)
		return batch


class IngestItemRepository:
	def __init__(self, session: Session) -> None:
		self._session = session

	def add(self, item: IngestItem) -> IngestItem:
		self._session.add(item)
		return item

	def set_status(
		self,
		*,
		item_id: uuid.UUID,
		status: str,
		error_code: Optional[str] = None,
		error_message: Optional[str] = None,
		result_policy_version_id: Optional[uuid.UUID] = None,
	) -> None:
		item = self._session.get(IngestItem, item_id)
		if item is None:
			return
		item.status = status
		item.error_code = error_code
		item.error_message = error_message
		if result_policy_version_id is not None:
			item.result_policy_version_id = result_policy_version_id

	@staticmethod
	def is_integrity_error(exc: Exception) -> bool:
		return isinstance(exc, IntegrityError)
