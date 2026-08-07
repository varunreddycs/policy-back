from __future__ import annotations

import uuid
from typing import Any, Dict

from packages.core.dtos import AnswerResponse, AskRequest
from packages.core.errors import DomainError
from packages.db.repositories.base import IAuditRepository


class AuditNotFound(DomainError):
    def __init__(self, audit_id: uuid.UUID) -> None:
        super().__init__(code="AUDIT_NOT_FOUND", message="Audit record not found", detail={"audit_id": str(audit_id)})


class AuditService:
    """Accepts either an IAuditRepository (new path) or a raw Session (backward compat)."""

    def __init__(self, *, audit_repo: IAuditRepository | None = None, session: Any = None) -> None:
        if audit_repo is not None:
            self._repo = audit_repo
        elif session is not None:
            from packages.db.repositories.audit_repo import PgAuditRepository

            self._repo = PgAuditRepository(session)
        else:
            raise ValueError("AuditService requires either audit_repo or session")

    def write(self, *, tenant_id: uuid.UUID, event_type: str, correlation_id: str | None, payload: Dict[str, Any]) -> uuid.UUID:
        return self._repo.write(
            tenant_id=tenant_id,
            event_type=event_type,
            correlation_id=correlation_id,
            payload=payload,
        )

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

    def get(self, *, tenant_id: uuid.UUID, audit_id: uuid.UUID) -> Dict[str, Any]:
        dto = self._repo.get_by_id(tenant_id=tenant_id, audit_id=audit_id)
        if dto is None:
            raise AuditNotFound(audit_id)
        return {
            "id": dto.id,
            "tenant_id": dto.tenant_id,
            "correlation_id": dto.correlation_id,
            "event_type": dto.event_type,
            "created_at": dto.created_at,
            "request": dto.payload.get("request"),
            "response": dto.payload.get("response"),
            "payload": dto.payload,
        }

    def replay(self, *, tenant_id: uuid.UUID, audit_id: uuid.UUID, ask_service: Any) -> Dict[str, Any]:
        record = self.get(tenant_id=tenant_id, audit_id=audit_id)
        request_payload = record.get("payload", {}).get("request")
        if not isinstance(request_payload, dict):
            raise DomainError(code="AUDIT_INVALID", message="Audit record does not contain an ask request")

        request = AskRequest.model_validate(request_payload)  # type: ignore[attr-defined]
        response = ask_service.ask(request)
        if not response.audit_id:
            response = response.model_copy(update={"audit_id": self.write_ask(request=request, response=response)})  # type: ignore[attr-defined]

        return {"replay_audit_id": response.audit_id, "response": response}
