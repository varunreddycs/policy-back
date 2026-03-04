from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Tuple

from packages.core.dtos import AnswerResponse, AskRequest, CitationItem, DecisionInfo, EvidenceCandidate, SecondaryEvidenceItem
from packages.ranking.ranker import PolicyRanker
from packages.retrieval.base import IVectorRetriever


class AnswerService:
	"""Orchestrates retrieval + ranking + (future) LLM call + citations."""

	def __init__(self, retriever: IVectorRetriever, ranker: PolicyRanker | None = None) -> None:
		self._retriever = retriever
		self._ranker = ranker or PolicyRanker()

	@staticmethod
	def _norm_dept(value: object | None) -> str:
		if value is None:
			return "all"
		text = str(value).strip().lower()
		return text or "all"

	@staticmethod
	def _extract_user_department(candidates: List[EvidenceCandidate]) -> str | None:
		for item in candidates:
			dept = (item.metadata or {}).get("user_department")
			if dept is None:
				continue
			dept_norm = str(dept).strip().lower()
			if dept_norm:
				return dept_norm
		return None

	def _bucket_candidates(
		self,
		candidates: List[EvidenceCandidate],
		user_department: str | None,
	) -> Tuple[List[EvidenceCandidate], List[EvidenceCandidate], str, str]:
		bucket_a: List[EvidenceCandidate] = []
		bucket_b: List[EvidenceCandidate] = []
		for item in candidates:
			dept_scope = self._norm_dept((item.metadata or {}).get("department_scope"))
			if user_department and dept_scope == user_department:
				bucket_a.append(item)
			elif dept_scope == "all":
				bucket_b.append(item)

		if bucket_a:
			return bucket_a, bucket_b, "department_specific", "department bucket had direct matches"
		return bucket_b, bucket_a, "org_wide", "no department matches; fell back to org-wide bucket"

	@staticmethod
	def _clip_snippet(text: str, max_chars: int = 280) -> str:
		snippet = (text or "").strip().replace("\n", " ")
		if len(snippet) <= max_chars:
			return snippet
		return snippet[:max_chars].rstrip() + "..."

	def ask(self, request: AskRequest) -> AnswerResponse:
		user = request.user
		if user is not None and user.tenant_id != request.tenant_id:
			# Defensive: request must be tenant-scoped
			user = user.model_copy(update={"tenant_id": request.tenant_id})  # type: ignore[attr-defined]

		top_k = max(
			10,
			int(os.getenv("EMBEDDINGS_TOP_K", "40") or "40"),
			int(os.getenv("FTS_TOP_K", "40") or "40"),
		)

		candidates = self._retriever.retrieve(
			tenant_id=request.tenant_id,
			query=request.question,
			scope=request.scope,
			user=user,
			top_k=top_k,
		)
		user_department = self._extract_user_department(candidates)
		primary_pool, secondary_pool, selected_bucket, reason = self._bucket_candidates(candidates, user_department)
		ranked_primary = self._ranker.rank(primary_pool)
		ranked_secondary = self._ranker.rank(secondary_pool) if secondary_pool else []
		created_at = datetime.now(timezone.utc)
		if not ranked_primary:
			return AnswerResponse(
				answer="Insufficient evidence in available policy sections.",
				refusal_reason="insufficient_evidence",
				evidence=[],
				citations=[],
				citation_items=[],
				secondary_evidence=[],
				created_at=created_at,
			)

		best = ranked_primary[0]
		excerpt = (best.text or "").strip().replace("\n", " ")
		if len(excerpt) > 600:
			excerpt = excerpt[:600].rstrip() + "…"

		citation_items = [
			CitationItem(
				policy_id=item.policy_id,
				policy_version_id=item.policy_version_id,
				section_id=item.section_id,
				policy_name=(item.metadata or {}).get("policy_name"),
				section_title=(item.metadata or {}).get("title"),
				section_path=(item.metadata or {}).get("section_path"),
				snippet=self._clip_snippet(item.text),
				score=float(item.score or 0.0),
				public_url=(item.metadata or {}).get("public_url"),
			)
			for item in ranked_primary[:5]
		]

		citation = f"[policy_version_id={best.policy_version_id} section_id={best.section_id}]"
		answer = f"Most relevant excerpt: {excerpt} {citation}"
		citations = [
			f"[policy_version_id={item.policy_version_id} section_id={item.section_id}]"
			for item in ranked_primary[:3]
		]
		secondary_evidence = [
			SecondaryEvidenceItem(
				policy_version_id=item.policy_version_id,
				section_id=item.section_id,
				policy_name=(item.metadata or {}).get("policy_name"),
				section_title=(item.metadata or {}).get("title"),
				score=float(item.score or 0.0),
				department_scope=(item.metadata or {}).get("department_scope"),
				public_url=(item.metadata or {}).get("public_url"),
			)
			for item in ranked_secondary[:3]
		]
		decision = DecisionInfo(
			selected_bucket=selected_bucket,
			reason=reason,
			user_department=user_department,
			primary_candidates=len(primary_pool),
			secondary_candidates=len(secondary_pool),
		)
		return AnswerResponse(
			answer=answer,
			evidence=ranked_primary,
			citations=citations,
			citation_items=citation_items,
			decision=decision,
			secondary_evidence=secondary_evidence,
			confidence=0.5,
			created_at=created_at,
		)

