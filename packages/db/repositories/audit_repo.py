"""PostgreSQL implementation of IAuditRepository."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models.governance import AuditLog
from packages.db.repositories.base import IAuditRepository
from packages.db.repositories.repo_dtos import AuditLogDTO


def _audit_to_dto(row: AuditLog) -> AuditLogDTO:
    return AuditLogDTO(
        id=row.id,
        tenant_id=row.tenant_id,
        event_type=row.event_type,
        payload=dict(row.payload_json or {}),
        correlation_id=row.correlation_id,
        created_at=row.created_at,
    )


class PgAuditRepository(IAuditRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def write(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        correlation_id: Optional[str],
        payload: Dict[str, Any],
    ) -> uuid.UUID:
        row = AuditLog(
            tenant_id=tenant_id,
            event_type=event_type,
            correlation_id=correlation_id,
            payload_json=payload,
        )
        self._session.add(row)
        self._session.commit()
        return row.id

    def get_by_id(self, *, audit_id: uuid.UUID) -> Optional[AuditLogDTO]:
        row = self._session.execute(
            select(AuditLog).where(AuditLog.id == audit_id)
        ).scalar_one_or_none()
        return _audit_to_dto(row) if row else None

    def list_for_tenant(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> List[AuditLogDTO]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_audit_to_dto(r) for r in self._session.execute(stmt).scalars().all()]
