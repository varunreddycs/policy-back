"""PostgreSQL implementation of IPolicyVersionRepository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.db.models.policy_models import PolicyVersion
from packages.db.repositories.base import IPolicyVersionRepository
from packages.db.repositories.repo_dtos import PolicyVersionDTO


def _version_to_dto(v: PolicyVersion) -> PolicyVersionDTO:
    return PolicyVersionDTO(
        id=v.id,
        tenant_id=v.tenant_id,
        policy_id=v.policy_id,
        version_number=v.version_number,
        version_label=v.version_label,
        supersedes_policy_version_id=v.supersedes_policy_version_id,
        title=v.title,
        effective_date=v.effective_date,
        blob_container=v.blob_container,
        blob_name=v.blob_name,
        blob_version_id=v.blob_version_id,
        blob_etag=v.blob_etag,
        content_type=v.content_type,
        content_length=v.content_length,
        extracted_blob_container=v.extracted_blob_container,
        extracted_blob_name=v.extracted_blob_name,
        extracted_blob_uri=v.extracted_blob_uri,
        content_sha256=v.content_sha256,
        metadata_json=dict(v.metadata_json or {}),
        metadata_sha256=v.metadata_sha256,
        ingest_batch_id=v.ingest_batch_id,
        parse_status=v.parse_status,
        is_current=v.is_current,
        parse_status_updated_at=v.parse_status_updated_at,
        parse_error_code=v.parse_error_code,
        parse_error_message=v.parse_error_message,
        created_at=v.created_at,
        created_by_user_id=v.created_by_user_id,
        correlation_id=v.correlation_id,
    )


class PgPolicyVersionRepository(IPolicyVersionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, *, version_id: uuid.UUID) -> Optional[PolicyVersionDTO]:
        v = self._session.get(PolicyVersion, version_id)
        return _version_to_dto(v) if v else None

    def list_for_policy(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> List[PolicyVersionDTO]:
        stmt = (
            select(PolicyVersion)
            .where(PolicyVersion.tenant_id == tenant_id, PolicyVersion.policy_id == policy_id)
            .order_by(PolicyVersion.version_number.desc())
        )
        return [_version_to_dto(v) for v in self._session.execute(stmt).scalars().all()]

    def exists_duplicate(
        self, *, policy_id: uuid.UUID, content_sha256: str, metadata_sha256: str
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

    def create(self, **fields: Any) -> PolicyVersionDTO:
        v = PolicyVersion(**fields)
        self._session.add(v)
        self._session.flush()
        self._session.refresh(v)
        return _version_to_dto(v)

    def set_parse_status(
        self,
        *,
        version_id: uuid.UUID,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        v = self._session.get(PolicyVersion, version_id)
        if v is None:
            return
        v.parse_status = status
        v.parse_status_updated_at = datetime.now(timezone.utc)
        v.parse_error_code = error_code
        v.parse_error_message = error_message
        self._session.add(v)
        self._session.flush()

    def set_current(self, *, policy_id: uuid.UUID, version_id: uuid.UUID) -> None:
        self._session.execute(
            update(PolicyVersion).where(PolicyVersion.policy_id == policy_id).values(is_current=False)
        )
        self._session.execute(
            update(PolicyVersion).where(PolicyVersion.id == version_id).values(is_current=True)
        )
        self._session.flush()

    def set_extracted_blob(
        self,
        *,
        version_id: uuid.UUID,
        extracted_blob_container: str,
        extracted_blob_name: str,
        extracted_blob_uri: str,
    ) -> None:
        v = self._session.get(PolicyVersion, version_id)
        if v is None:
            return
        v.extracted_blob_container = extracted_blob_container
        v.extracted_blob_name = extracted_blob_name
        v.extracted_blob_uri = extracted_blob_uri
        self._session.add(v)
        self._session.flush()
