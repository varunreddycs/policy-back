from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from packages.core.dtos import AnswerResponse, AskRequest, CitationItem, DecisionInfo, EvidenceCandidate, SecondaryEvidenceItem
from packages.governance.prompt_registry import default_registry
from packages.llm.client import LlmClient, REFUSAL_PHRASE
from packages.ranking.ranker import PolicyRanker
from packages.retrieval.base import IVectorRetriever


logger = logging.getLogger(__name__)

_FALLBACK_SYSTEM_PROMPT = (
    "You are a compliance assistant grounded in the provided policy/control excerpts.\n\n"
    "Rules:\n"
    "1) Use only the provided evidence excerpts; do not invent requirements.\n"
    "2) Provide a concise, helpful answer that synthesizes the most relevant evidence, "
    "then a short bullet list of the controls/sections you cited (by their identifier, e.g. AC-2).\n"
    "3) If the evidence is relevant to the question, answer from the most relevant excerpts "
    "even when it is not a perfect match.\n"
    "4) Only if none of the provided evidence is relevant to the question, refuse with exactly: "
    '"Insufficient evidence in available policy sections."\n'
)


class AnswerService:
    """Orchestrates retrieval + ranking + LLM answer + citations."""

    def __init__(
        self,
        retriever: IVectorRetriever,
        ranker: PolicyRanker | None = None,
        llm: LlmClient | None = None,
    ) -> None:
        self._retriever = retriever
        self._ranker = ranker or PolicyRanker()
        self._llm = llm or LlmClient()
        try:
            self._registry = default_registry()
        except Exception:
            self._registry = None  # type: ignore[assignment]

    def _system_prompt(self) -> str:
        if self._registry is not None:
            try:
                return self._registry.get("strict_citation", "v2").template
            except KeyError:
                pass
        return _FALLBACK_SYSTEM_PROMPT

    @staticmethod
    def _norm_dept(value: object | None) -> str:
        if value is None:
            return "all"
        text = str(value).strip().lower()
        return text or "all"

    @staticmethod
    def _extract_user_department(candidates: List[EvidenceCandidate]) -> str | None:
        """Fallback: read user_department from retrieval metadata if not in request."""
        for item in candidates:
            dept = (item.metadata or {}).get("user_department")
            if dept is None:
                continue
            dept_norm = str(dept).strip().lower()
            if dept_norm:
                return dept_norm
        return None

    def _resolve_user_department(
        self,
        request: AskRequest,
        candidates: List[EvidenceCandidate],
    ) -> str | None:
        """Prefer request.user.department; fall back to metadata round-trip."""
        if request.user and request.user.department:
            dept = request.user.department.strip().lower()
            if dept:
                return dept
        return self._extract_user_department(candidates)

    def _bucket_candidates(
        self,
        candidates: List[EvidenceCandidate],
        user_department: str | None,
    ) -> Tuple[List[EvidenceCandidate], List[EvidenceCandidate], str, str]:
        bucket_a: List[EvidenceCandidate] = []   # user's dept-specific
        bucket_b: List[EvidenceCandidate] = []   # org-wide ("all")
        bucket_c: List[EvidenceCandidate] = []   # other dept-specific (cross-dept)
        for item in candidates:
            dept_scope = self._norm_dept((item.metadata or {}).get("department_scope"))
            if user_department and dept_scope == user_department:
                bucket_a.append(item)
            elif dept_scope == "all":
                bucket_b.append(item)
            else:
                bucket_c.append(item)

        if bucket_a:
            # Dept-specific wins; secondary = org-wide + cross-dept (surfaces conflicts)
            return bucket_a, bucket_b + bucket_c, "department_specific", "department bucket had direct matches"
        if bucket_b:
            # No dept match; org-wide wins; secondary = cross-dept fallback
            return bucket_b, bucket_c, "org_wide", "no department matches; fell back to org-wide bucket"
        # Last resort: cross-dept evidence only
        return bucket_c, [], "other", "no department or org-wide matches; using cross-department evidence"

    @staticmethod
    def _build_retrieval_log(
        candidates: List[EvidenceCandidate],
        selected_bucket: str,
        primary_score: float,
    ) -> Dict[str, Any]:
        """Lift hybrid retriever debug counters off candidate metadata into a top-level log."""
        meta = (candidates[0].metadata or {}) if candidates else {}
        return {
            "fts_candidates": int(meta.get("hybrid_fts_candidates") or 0),
            "vector_candidates": int(meta.get("hybrid_vector_candidates") or 0),
            "merged": int(meta.get("hybrid_merged_candidates") or len(candidates)),
            "filtered": int(meta.get("hybrid_filtered_candidates") or len(candidates)),
            "selected_bucket": selected_bucket,
            "primary_score": float(primary_score),
        }

    @staticmethod
    def _clip_snippet(text: str, max_chars: int = 280) -> str:
        snippet = (text or "").strip().replace("\n", " ")
        if len(snippet) <= max_chars:
            return snippet
        return snippet[:max_chars].rstrip() + "..."

    @staticmethod
    def _build_user_message(question: str, candidates: List[EvidenceCandidate]) -> str:
        """Format evidence + question for the LLM."""
        lines = [f"Question: {question}", "", "Evidence:"]
        for i, c in enumerate(candidates, start=1):
            ref = f"[policy_version_id={c.policy_version_id} section_id={c.section_id}]"
            text = (c.text or "").strip().replace("\n", " ")
            if len(text) > 600:
                text = text[:600].rstrip() + "…"
            lines.append(f"[{i}] {ref} {text}")
        lines.append("")
        lines.append("Answer (cite using the format [policy_version_id=... section_id=...]):")
        return "\n".join(lines)

    def _call_llm(self, question: str, candidates: List[EvidenceCandidate]) -> str | None:
        """Call LLM; returns answer text or None if LLM not available."""
        if not self._llm.available:
            logger.info("llm.unavailable; using excerpt fallback")
            return None
        try:
            user_msg = self._build_user_message(question, candidates)
            return self._llm.complete(self._system_prompt(), user_msg)
        except Exception as exc:
            logger.warning("llm.call.failed", extra={"error": str(exc)})
            return None

    def ask(self, request: AskRequest) -> AnswerResponse:
        user = request.user
        if user is not None and user.tenant_id != request.tenant_id:
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

        user_department = self._resolve_user_department(request, candidates)
        primary_pool, secondary_pool, selected_bucket, reason = self._bucket_candidates(candidates, user_department)
        ranked_primary = self._ranker.rank(primary_pool)
        ranked_secondary = self._ranker.rank(secondary_pool) if secondary_pool else []
        created_at = datetime.now(timezone.utc)

        if not ranked_primary:
            return AnswerResponse(
                answer=REFUSAL_PHRASE,
                refusal_reason="insufficient_evidence",
                evidence=[],
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(candidates, selected_bucket, 0.0),
                confidence=0.0,
                created_at=created_at,
            )

        best = ranked_primary[0]
        primary_score_check = float(best.score or 0.0)

        # Phase 2.7 spec: refuse below confidence threshold even if we have candidates.
        refusal_threshold = float(os.getenv("ANSWER_REFUSAL_MIN_SCORE", "0.5") or "0.5")
        if primary_score_check < refusal_threshold:
            return AnswerResponse(
                answer=REFUSAL_PHRASE,
                refusal_reason="insufficient_evidence",
                evidence=ranked_primary,
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(ranked_primary, selected_bucket, primary_score_check),
                confidence=0.0,
                created_at=created_at,
            )

        hybrid_debug = best.metadata or {}
        logger.info(
            "retrieval.summary",
            extra={
                "fts_candidates": int(hybrid_debug.get("hybrid_fts_candidates") or 0),
                "vector_candidates": int(hybrid_debug.get("hybrid_vector_candidates") or 0),
                "merged_candidates": int(hybrid_debug.get("hybrid_merged_candidates") or len(candidates)),
                "selected_bucket": selected_bucket,
                "primary_score": float(best.score or 0.0),
            },
        )

        # LLM answer generation — falls back to excerpt if LLM not configured or fails.
        llm_answer = self._call_llm(request.question, ranked_primary[:5])

        if llm_answer and REFUSAL_PHRASE.lower() in llm_answer.lower():
            return AnswerResponse(
                answer=llm_answer,
                refusal_reason="insufficient_evidence",
                evidence=ranked_primary,
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(ranked_primary, selected_bucket, float(best.score or 0.0)),
                confidence=float(best.score or 0.0),
                created_at=created_at,
            )

        if llm_answer:
            answer = llm_answer
        else:
            # Excerpt fallback: plain-text citation without LLM.
            excerpt = (best.text or "").strip().replace("\n", " ")
            if len(excerpt) > 600:
                excerpt = excerpt[:600].rstrip() + "…"
            citation = f"[policy_version_id={best.policy_version_id} section_id={best.section_id}]"
            answer = f"{excerpt} {citation}"

        citations = [
            f"[policy_version_id={item.policy_version_id} section_id={item.section_id}]"
            for item in ranked_primary[:3]
        ]

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

        primary_score = float(best.score or 0.0)
        primary_department = self._norm_dept((best.metadata or {}).get("department_scope"))
        secondary_threshold = primary_score * 0.8
        secondary_filtered: List[EvidenceCandidate] = []
        for item in ranked_secondary:
            item_dept = self._norm_dept((item.metadata or {}).get("department_scope"))
            if item_dept == primary_department:
                continue
            if float(item.score or 0.0) < secondary_threshold:
                continue
            secondary_filtered.append(item)
            if len(secondary_filtered) >= 3:
                break

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
            for item in secondary_filtered
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
            retrieval_log=self._build_retrieval_log(ranked_primary, selected_bucket, primary_score),
            secondary_evidence=secondary_evidence,
            confidence=primary_score,
            created_at=created_at,
        )
