from __future__ import annotations

from sqlalchemy.orm import Session

from packages.core.dtos import AnswerResponse, AskRequest
from packages.governance.audit_service import AuditService
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever


class AskService:
    """Phase 2 orchestration: retrieve -> rank -> answer -> audit."""

    def __init__(self, *, session: Session, retriever: IVectorRetriever) -> None:
        self._session = session
        self._answer = AnswerService(retriever=retriever)
        self._audit = AuditService(session=session)

    def ask(self, request: AskRequest) -> AnswerResponse:
        response = self._answer.ask(request)
        audit_id = self._audit.write_ask(request=request, response=response)
        return response.model_copy(update={"audit_id": audit_id})  # type: ignore[attr-defined]
