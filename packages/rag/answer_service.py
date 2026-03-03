from __future__ import annotations

from datetime import datetime, timezone

from packages.core.dtos import AnswerResponse, AskRequest
from packages.ranking.ranker import PolicyRanker
from packages.retrieval.base import IVectorRetriever


class AnswerService:
	"""Orchestrates retrieval + ranking + (future) LLM call + citations."""

	def __init__(self, retriever: IVectorRetriever, ranker: PolicyRanker | None = None) -> None:
		self._retriever = retriever
		self._ranker = ranker or PolicyRanker()

	def ask(self, request: AskRequest) -> AnswerResponse:
		candidates = self._retriever.retrieve(tenant_id=request.tenant_id, query=request.question, limit=10)
		ranked = self._ranker.rank(candidates)
		# Phase 2: produce answer via LLM; Phase 1 scaffold returns empty answer.
		return AnswerResponse(answer="", evidence=ranked, created_at=datetime.now(timezone.utc))
