from __future__ import annotations

from typing import Any

from packages.core.dtos import AnswerResponse, AskRequest
from packages.db.repositories.base import IAuditRepository
from packages.governance.audit_service import AuditService
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever


class AskService:
    """Phase 2 orchestration: retrieve -> rank -> answer -> audit."""

    def __init__(
        self,
        *,
        retriever: IVectorRetriever,
        session: Any = None,
        audit_repo: IAuditRepository | None = None,
    ) -> None:
        self._answer = AnswerService(retriever=retriever)
        if audit_repo is not None:
            self._audit = AuditService(audit_repo=audit_repo)
        elif session is not None:
            self._audit = AuditService(session=session)
        else:
            raise ValueError("AskService requires either audit_repo or session")

    def ask(self, request: AskRequest) -> AnswerResponse:
        response = self._answer.ask(request)
        audit_id = self._audit.write_ask(request=request, response=response)
        return response.model_copy(update={"audit_id": audit_id})  # type: ignore[attr-defined]
