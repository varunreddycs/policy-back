"""PostgreSQL implementations of IIngestBatchRepository and IIngestItemRepository."""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.db.models.policy_models import IngestBatch, IngestItem
from packages.db.repositories.base import IIngestBatchRepository, IIngestItemRepository
from packages.db.repositories.repo_dtos import IngestBatchDTO, IngestItemDTO


def _batch_to_dto(b: IngestBatch) -> IngestBatchDTO:
    return IngestBatchDTO(
        id=b.id,
        tenant_id=b.tenant_id,
        status=b.status,
        submitted_by_user_id=b.submitted_by_user_id,
        source_system=b.source_system,
        status_reason=b.status_reason,
        correlation_id=b.correlation_id,
        created_at=b.created_at,
        updated_at=b.updated_at,
    )


def _item_to_dto(i: IngestItem) -> IngestItemDTO:
    return IngestItemDTO(
        id=i.id,
        tenant_id=i.tenant_id,
        batch_id=i.batch_id,
        status=i.status,
        policy_id=i.policy_id,
        blob_container=i.blob_container,
        blob_name=i.blob_name,
        content_sha256=i.content_sha256,
        metadata_json=dict(i.metadata_json or {}),
        metadata_sha256=i.metadata_sha256,
        correlation_id=i.correlation_id,
        error_code=i.error_code,
        error_message=i.error_message,
        result_policy_version_id=i.result_policy_version_id,
        created_at=i.created_at,
        updated_at=i.updated_at,
    )


class PgIngestBatchRepository(IIngestBatchRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, batch_id: uuid.UUID) -> Optional[IngestBatchDTO]:
        b = self._session.get(IngestBatch, batch_id)
        return _batch_to_dto(b) if b else None

    def create(self, **fields: Any) -> IngestBatchDTO:
        b = IngestBatch(**fields)
        self._session.add(b)
        self._session.flush()
        self._session.refresh(b)
        return _batch_to_dto(b)

    def update_status(self, *, batch_id: uuid.UUID, status: str) -> None:
        b = self._session.get(IngestBatch, batch_id)
        if b is None:
            return
        b.status = status
        self._session.add(b)
        self._session.flush()


class PgIngestItemRepository(IIngestItemRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **fields: Any) -> IngestItemDTO:
        i = IngestItem(**fields)
        self._session.add(i)
        self._session.flush()
        self._session.refresh(i)
        return _item_to_dto(i)

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
        self._session.flush()

    def set_status_by_result_version(
        self,
        *,
        policy_version_id: uuid.UUID,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self._session.execute(
            update(IngestItem)
            .where(IngestItem.result_policy_version_id == policy_version_id)
            .values(
                status=status,
                error_code=error_code,
                error_message=error_message,
                updated_at=func.now(),
            )
        )
        self._session.flush()

    def count_active_for_batch(self, *, batch_id: uuid.UUID) -> int:
        result = self._session.execute(
            select(func.count(IngestItem.id)).where(
                IngestItem.batch_id == batch_id,
                IngestItem.status.in_(["received", "queued", "processing"]),
            )
        ).scalar_one()
        return int(result)
