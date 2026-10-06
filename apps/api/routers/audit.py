from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.deps import get_audit_service, get_ask_service
from apps.api.errors import map_domain_error
from apps.api.schemas.audit import AuditLogResponse, ReplayResponse
from packages.governance.audit_service import AuditNotFound, AuditService
from packages.rag.ask_service import AskService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Audit"])


def _not_found() -> HTTPException:
    """Generic 404 used for both missing and cross-tenant audit rows.

    Returning an identical response for "does not exist" and "belongs to another
    tenant" prevents a cross-tenant existence oracle.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": "Audit record not found"},
    )


@router.get(
    "/audit/{audit_id}",
    response_model=AuditLogResponse,
    summary="Get audit log",
)
def get_audit_log(
    audit_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    audit_service: AuditService = Depends(get_audit_service),
) -> AuditLogResponse:
    try:
        return audit_service.get(tenant_id=tenant_id, audit_id=audit_id)
    except AuditNotFound:
        raise _not_found()
    except Exception as exc:
        logger.exception("api.audit.get_failed", extra={"audit_id": str(audit_id)})
        raise map_domain_error(exc)


@router.post(
    "/audit/{audit_id}/replay",
    response_model=ReplayResponse,
    summary="Replay an audited ask",
    description="Replays a prior ask request from the audit log and writes a new audit record.",
)
def replay_audit(
    audit_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    audit_service: AuditService = Depends(get_audit_service),
    ask_service: AskService = Depends(get_ask_service),
) -> ReplayResponse:
    try:
        response = audit_service.replay(
            tenant_id=tenant_id, audit_id=audit_id, ask_service=ask_service
        )
        return response
    except AuditNotFound:
        raise _not_found()
    except Exception as exc:
        logger.exception("api.audit.replay_failed", extra={"audit_id": str(audit_id)})
        raise map_domain_error(exc)
