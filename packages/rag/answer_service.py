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
		user = request.user
		if user is not None and user.tenant_id != request.tenant_id:
			# Defensive: request must be tenant-scoped
			user = user.model_copy(update={"tenant_id": request.tenant_id})  # type: ignore[attr-defined]

		candidates = self._retriever.retrieve(
			tenant_id=request.tenant_id,
			query=request.question,
			scope=request.scope,
			user=user,
			top_k=10,
		)
		ranked = self._ranker.rank(candidates)
		created_at = datetime.now(timezone.utc)
		if not ranked:
			return AnswerResponse(
				answer="Insufficient evidence in available policy sections.",
				refusal_reason="insufficient_evidence",
				evidence=[],
				citations=[],
				created_at=created_at,
			)

		best = ranked[0]
		excerpt = (best.text or "").strip().replace("\n", " ")
		if len(excerpt) > 600:
			excerpt = excerpt[:600].rstrip() + "…"

		citation = f"[policy_version_id={best.policy_version_id} section_id={best.section_id}]"
		answer = f"Most relevant excerpt: {excerpt} {citation}"
		citations = [citation]
		return AnswerResponse(
			answer=answer,
			evidence=ranked,
			citations=citations,
			confidence=0.5,
			created_at=created_at,
		)

