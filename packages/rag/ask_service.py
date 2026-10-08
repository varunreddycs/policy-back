from __future__ import annotations

import logging
from typing import Any

from packages.core.dtos import AnswerResponse, AskRequest
from packages.db.repositories.base import IAuditRepository, IReferenceRepository
from packages.governance.audit_service import AuditService
from packages.rag.answer_service import AnswerService
from packages.rag.related_controls import enrich_citations
from packages.retrieval.base import IVectorRetriever

logger = logging.getLogger(__name__)


class AskService:
    """Phase 2 orchestration: retrieve -> rank -> answer -> audit."""

    def __init__(
        self,
        *,
        retriever: IVectorRetriever,
        session: Any = None,
        audit_repo: IAuditRepository | None = None,
        references_repo: IReferenceRepository | None = None,
    ) -> None:
        self._answer = AnswerService(retriever=retriever)
        self._references = references_repo
        if audit_repo is not None:
            self._audit = AuditService(audit_repo=audit_repo)
        elif session is not None:
            self._audit = AuditService(session=session)
        else:
            raise ValueError("AskService requires either audit_repo or session")

    def ask(self, request: AskRequest) -> AnswerResponse:
        response = self._attach_related_controls(request, self._answer.ask(request))
        audit_id = self._audit.write_ask(request=request, response=response)
        return response.model_copy(update={"audit_id": audit_id})  # type: ignore[attr-defined]

    def _attach_related_controls(self, request: AskRequest, response: AnswerResponse) -> AnswerResponse:
        if self._references is None or not response.citation_items:
            return response
        try:
            items = enrich_citations(
                response.citation_items, references_repo=self._references, tenant_id=request.tenant_id
            )
        except Exception:
            # Display-only metadata: a crosswalk lookup failure must never fail or alter an answer.
            logger.warning("related_controls_lookup_failed", exc_info=True)
            return response
        return response.model_copy(update={"citation_items": items})
