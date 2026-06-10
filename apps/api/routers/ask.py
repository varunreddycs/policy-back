from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from apps.api.deps import get_ask_service
from apps.api.errors import map_domain_error
from packages.core.dtos import AnswerResponse, AskRequest
from packages.rag.ask_service import AskService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Ask"])


@router.post(
    "/ask",
    response_model=AnswerResponse,
    summary="Ask a question",
    description="Phase 2: retrieve evidence and produce an answer with audit traceability.",
)
def ask_policy(request: AskRequest, service: AskService = Depends(get_ask_service)) -> AnswerResponse:
    try:
        return service.ask(request)
    except Exception as exc:
        logger.exception("api.ask_failed")
        raise map_domain_error(exc)
