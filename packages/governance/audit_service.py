from __future__ import annotations

import uuid
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.dtos import AnswerResponse, AskRequest
from packages.core.errors import DomainError
from packages.db.models.governance import AuditLog


class AuditNotFound(DomainError):
    def __init__(self, audit_id: uuid.UUID) -> None:
        super().__init__(code="AUDIT_NOT_FOUND", message="Audit record not found", detail={"audit_id": str(audit_id)})


class AuditService:
    def __init__(self, *, session: Session) -> None:
        self._session = session

    def write(self, *, tenant_id: uuid.UUID, event_type: str, correlation_id: str | None, payload: Dict[str, Any]) -> uuid.UUID:
        row = AuditLog(tenant_id=tenant_id, event_type=event_type, correlation_id=correlation_id, payload_json=payload)
        self._session.add(row)
        self._session.commit()
        return row.id

    def write_ask(self, *, request: AskRequest, response: AnswerResponse) -> uuid.UUID:
        payload = {
            "request": request.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
        }
        return self.write(
            tenant_id=request.tenant_id,
            event_type="ask",
            correlation_id=request.correlation_id,
            payload=payload,
        )

    def get(self, *, audit_id: uuid.UUID) -> Dict[str, Any]:
        row = self._session.execute(select(AuditLog).where(AuditLog.id == audit_id)).scalar_one_or_none()
        if row is None:
            raise AuditNotFound(audit_id)
        payload = dict(row.payload_json or {})
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "correlation_id": row.correlation_id,
            "event_type": row.event_type,
            "created_at": row.created_at,
            "request": payload.get("request"),
            "response": payload.get("response"),
            "payload": payload,
        }

    def replay(self, *, audit_id: uuid.UUID, ask_service: Any) -> Dict[str, Any]:
        record = self.get(audit_id=audit_id)
        request_payload = record.get("payload", {}).get("request")
        if not isinstance(request_payload, dict):
            raise DomainError(code="AUDIT_INVALID", message="Audit record does not contain an ask request")

        request = AskRequest.model_validate(request_payload)  # type: ignore[attr-defined]
        response = ask_service.ask(request)
        if not response.audit_id:
            # Defensive fallback in case caller bypassed AskService.
            response = response.model_copy(update={"audit_id": self.write_ask(request=request, response=response)})  # type: ignore[attr-defined]

        return {"replay_audit_id": response.audit_id, "response": response}
