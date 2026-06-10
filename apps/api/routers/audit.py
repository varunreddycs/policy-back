from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends

from apps.api.deps import get_audit_service, get_ask_service
from apps.api.errors import map_domain_error
from apps.api.schemas.audit import AuditLogResponse, ReplayResponse
from packages.governance.audit_service import AuditService
from packages.rag.ask_service import AskService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Audit"])


@router.get(
    "/audit/{audit_id}",
    response_model=AuditLogResponse,
    summary="Get audit log",
)
def get_audit_log(
    audit_id: uuid.UUID,
    audit_service: AuditService = Depends(get_audit_service),
) -> AuditLogResponse:
    try:
        return audit_service.get(audit_id=audit_id)
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
    audit_service: AuditService = Depends(get_audit_service),
    ask_service: AskService = Depends(get_ask_service),
) -> ReplayResponse:
    try:
        response = audit_service.replay(audit_id=audit_id, ask_service=ask_service)
        return response
    except Exception as exc:
        logger.exception("api.audit.replay_failed", extra={"audit_id": str(audit_id)})
        raise map_domain_error(exc)
