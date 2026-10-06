from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from packages.core.dtos import (
    AnswerResponse,
    AnswerSource,
    AskRequest,
    CitationItem,
    DecisionInfo,
    EvidenceCandidate,
    RefusalCode,
    RefusalInfo,
    SecondaryEvidenceItem,
)
from packages.governance.prompt_registry import default_registry
from packages.llm.client import REFUSAL_PHRASE, LlmClient, LlmError
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
    def _extract_user_department(candidates: list[EvidenceCandidate]) -> str | None:
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
        candidates: list[EvidenceCandidate],
    ) -> str | None:
        """Prefer request.user.department; fall back to metadata round-trip."""
        if request.user and request.user.department:
            dept = request.user.department.strip().lower()
            if dept:
                return dept
        return self._extract_user_department(candidates)

    def _bucket_candidates(
        self,
        candidates: list[EvidenceCandidate],
        user_department: str | None,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], str, str]:
        bucket_a: list[EvidenceCandidate] = []  # user's dept-specific
        bucket_b: list[EvidenceCandidate] = []  # org-wide ("all")
        bucket_c: list[EvidenceCandidate] = []  # other dept-specific (cross-dept)
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
            return (
                bucket_a,
                bucket_b + bucket_c,
                "department_specific",
                "department bucket had direct matches",
            )
        if bucket_b:
            # No dept match; org-wide wins; secondary = cross-dept fallback
            return (
                bucket_b,
                bucket_c,
                "org_wide",
                "no department matches; fell back to org-wide bucket",
            )
        # Last resort: cross-dept evidence only
        return (
            bucket_c,
            [],
            "other",
            "no department or org-wide matches; using cross-department evidence",
        )

    @staticmethod
    def _grounding_score(candidate: EvidenceCandidate) -> float | None:
        """The value ANSWER_REFUSAL_MIN_SCORE is compared against.

        Q5: the fused hybrid score is batch-relative — the top candidate trends
        toward the weight ceiling regardless of how well it actually matched —
        so gating on it means the 0.5 threshold denotes something different per
        backend. Only a true cosine similarity is comparable against an absolute
        threshold.

        Returns None when no absolute measure exists, which is not the same as
        scoring zero: a section that only full-text search surfaced has no
        similarity at all, and gating its *fused rank* against a cosine
        threshold would refuse good lexical matches — the exact cross-backend
        mis-calibration this was meant to remove.
        """
        md = candidate.metadata or {}
        similarity = md.get("vector_similarity")
        if isinstance(similarity, (int, float)):
            return float(similarity)
        # Fused scores are rank-derived, not similarities; refuse to pretend.
        if md.get("fusion") == "rrf" or md.get("retriever") == "hybrid":
            return None
        # Non-hybrid backends (pgvector, cosmos) put a true cosine on score.
        return float(candidate.score or 0.0)

    @staticmethod
    def _distinct_versions(candidates: list[EvidenceCandidate]) -> int:
        return len({item.policy_version_id for item in candidates})

    @staticmethod
    def _classify_empty_primary(
        candidates: list[EvidenceCandidate],
        user_department: str | None,
    ) -> tuple[RefusalCode, str]:
        """No primary evidence survived bucketing.

        Bucket C is a catch-all, so a non-empty retrieval always produces a primary
        pool; reaching here with candidates means every one was discarded downstream.
        """
        if not candidates:
            return (
                RefusalCode.NO_AUTHORITATIVE_CONTROL,
                "No policy section in scope matched the question, so no authoritative control could be cited.",
            )
        scope = f"'{user_department}'" if user_department else "the asking department"
        return (
            RefusalCode.DEPARTMENT_SCOPE_AMBIGUOUS,
            (
                f"{len(candidates)} section(s) matched but none could be attributed to {scope} "
                "or to an organization-wide scope, so no authoritative control applies."
            ),
        )

    @staticmethod
    def _refusal(
        code: RefusalCode,
        explanation: str,
        *,
        selected_bucket: str | None,
        user_department: str | None,
        candidates_considered: int,
        best_score: float | None = None,
        threshold: float | None = None,
    ) -> RefusalInfo:
        return RefusalInfo(
            code=code,
            explanation=explanation,
            selected_bucket=selected_bucket,
            user_department=user_department,
            candidates_considered=candidates_considered,
            best_score=best_score,
            threshold=threshold,
        )

    @staticmethod
    def _build_retrieval_log(
        candidates: list[EvidenceCandidate],
        selected_bucket: str,
        primary_score: float,
    ) -> dict[str, Any]:
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
    def _build_user_message(question: str, candidates: list[EvidenceCandidate]) -> str:
        """Format evidence + question for the LLM."""
        lines = [f"Question: {question}", "", "Evidence:"]
        for i, c in enumerate(candidates, start=1):
            ref = f"[policy_version_id={c.policy_version_id} section_id={c.section_id}]"
            text = (c.text or "").strip().replace("\n", " ")
            if len(text) > 600:
                text = text[:600].rstrip() + "…"
            lines.append(f"[{i}] {ref} {text}")
        lines.append("")
        lines.append(
            "Answer (cite using the format [policy_version_id=... section_id=...]):"
        )
        return "\n".join(lines)

    def _call_llm(
        self, question: str, candidates: list[EvidenceCandidate]
    ) -> tuple[str | None, str | None]:
        """Generate an answer.

        Returns (answer_text, degradation_reason). A non-None reason means the
        caller must fall back to an excerpt and surface that on the response —
        Q2: a silently degraded compliance answer is worse than a flagged one.
        """
        if not self._llm.available:
            logger.info("llm.unavailable; using excerpt fallback")
            return None, "llm_not_configured"
        try:
            user_msg = self._build_user_message(question, candidates)
            completion = self._llm.complete_detailed(self._system_prompt(), user_msg)
        except LlmError as exc:
            logger.warning(
                "llm.call.failed",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None, f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # unexpected client fault; never fail the ask
            logger.exception("llm.call.unexpected_error", extra={"error": str(exc)})
            return None, f"{type(exc).__name__}: {exc}"

        logger.info(
            "llm.call.succeeded",
            extra={
                "finish_reason": completion.finish_reason,
                "attempts": completion.attempts,
                "completion_tokens": completion.completion_tokens,
            },
        )
        return completion.content, None

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
        primary_pool, secondary_pool, selected_bucket, reason = self._bucket_candidates(
            candidates, user_department
        )
        ranked_primary = self._ranker.rank(primary_pool)
        ranked_secondary = self._ranker.rank(secondary_pool) if secondary_pool else []
        created_at = datetime.now(timezone.utc)

        if not ranked_primary:
            code, explanation = self._classify_empty_primary(
                candidates, user_department
            )
            refusal = self._refusal(
                code,
                explanation,
                selected_bucket=selected_bucket,
                user_department=user_department,
                candidates_considered=len(candidates),
            )
            logger.info(
                "answer.refused",
                extra={"refusal_code": str(code), "selected_bucket": selected_bucket},
            )
            return AnswerResponse(
                answer=REFUSAL_PHRASE,
                refusal_reason=str(code),
                refusal=refusal,
                answer_source=AnswerSource.REFUSAL,
                evidence=[],
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(
                    candidates, selected_bucket, 0.0
                ),
                confidence=0.0,
                created_at=created_at,
            )

        best = ranked_primary[0]
        primary_score_check = self._grounding_score(best)

        # Phase 2.7 spec: refuse below confidence threshold even if we have candidates.
        # Q5: only gate when an absolute similarity exists — see _grounding_score.
        # A strong lexical-only match has no cosine to compare, and refusing it
        # against a cosine threshold would reject correct evidence.
        refusal_threshold = float(os.getenv("ANSWER_REFUSAL_MIN_SCORE", "0.5") or "0.5")
        if primary_score_check is not None and primary_score_check < refusal_threshold:
            # A weak match that also fell through to the cross-department bucket is a
            # scope finding, not just a scoring one — the officer needs to know no
            # policy owned by their department (or the org) covered the question.
            if selected_bucket == "other":
                code = RefusalCode.DEPARTMENT_SCOPE_AMBIGUOUS
                scope = (
                    f"'{user_department}'"
                    if user_department
                    else "the asking department"
                )
                explanation = (
                    f"Only cross-department evidence was available (best score "
                    f"{primary_score_check:.3f}); nothing scoped to {scope} or to the "
                    "organization applies to this question."
                )
            else:
                code = RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD
                explanation = (
                    f"Best matching section scored {primary_score_check:.3f}, below the "
                    f"{refusal_threshold:.3f} grounding threshold required to cite it as authoritative."
                )
            refusal = self._refusal(
                code,
                explanation,
                selected_bucket=selected_bucket,
                user_department=user_department,
                candidates_considered=len(ranked_primary),
                best_score=primary_score_check,
                threshold=refusal_threshold,
            )
            logger.info(
                "answer.refused",
                extra={
                    "refusal_code": str(code),
                    "selected_bucket": selected_bucket,
                    "best_score": primary_score_check,
                },
            )
            return AnswerResponse(
                answer=REFUSAL_PHRASE,
                refusal_reason=str(code),
                refusal=refusal,
                answer_source=AnswerSource.REFUSAL,
                evidence=ranked_primary,
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(
                    ranked_primary, selected_bucket, primary_score_check
                ),
                confidence=0.0,
                grounding_score=primary_score_check,
                created_at=created_at,
            )

        hybrid_debug = best.metadata or {}
        logger.info(
            "retrieval.summary",
            extra={
                "fts_candidates": int(hybrid_debug.get("hybrid_fts_candidates") or 0),
                "vector_candidates": int(
                    hybrid_debug.get("hybrid_vector_candidates") or 0
                ),
                "merged_candidates": int(
                    hybrid_debug.get("hybrid_merged_candidates") or len(candidates)
                ),
                "selected_bucket": selected_bucket,
                "primary_score": float(best.score or 0.0),
            },
        )

        # LLM answer generation — falls back to excerpt if LLM not configured or fails.
        llm_answer, llm_error = self._call_llm(request.question, ranked_primary[:5])

        if llm_answer and REFUSAL_PHRASE.lower() in llm_answer.lower():
            # The evidence cleared retrieval and grounding but the model still would not
            # answer from it. Competing versions of the same policy are the one signal we
            # can attribute; otherwise the cited controls simply do not cover the question.
            considered = ranked_primary[:5]
            if self._distinct_versions(considered) > 1 and len(
                {c.policy_id for c in considered}
            ) < len(considered):
                code = RefusalCode.CONFLICTING_VERSIONS
                explanation = (
                    "Evidence spans multiple versions of the same policy; the applicable "
                    "version could not be determined, so no single requirement was cited."
                )
            else:
                code = RefusalCode.NO_AUTHORITATIVE_CONTROL
                explanation = (
                    "Sections were retrieved and cleared the grounding threshold, but none "
                    "state a requirement that answers the question."
                )
            refusal = self._refusal(
                code,
                explanation,
                selected_bucket=selected_bucket,
                user_department=user_department,
                candidates_considered=len(ranked_primary),
                best_score=float(best.score or 0.0),
                threshold=refusal_threshold,
            )
            logger.info(
                "answer.refused",
                extra={
                    "refusal_code": str(code),
                    "selected_bucket": selected_bucket,
                    "gate": "llm",
                },
            )
            return AnswerResponse(
                answer=llm_answer,
                refusal_reason=str(code),
                refusal=refusal,
                answer_source=AnswerSource.REFUSAL,
                evidence=ranked_primary,
                citations=[],
                citation_items=[],
                secondary_evidence=[],
                retrieval_log=self._build_retrieval_log(
                    ranked_primary, selected_bucket, float(best.score or 0.0)
                ),
                confidence=float(best.score or 0.0),
                grounding_score=self._grounding_score(best),
                created_at=created_at,
            )

        if llm_answer:
            answer = llm_answer
            answer_source = AnswerSource.LLM
        else:
            answer_source = AnswerSource.EXCERPT_FALLBACK
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
        primary_department = self._norm_dept(
            (best.metadata or {}).get("department_scope")
        )
        secondary_threshold = primary_score * 0.8
        secondary_filtered: list[EvidenceCandidate] = []
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
            retrieval_log=self._build_retrieval_log(
                ranked_primary, selected_bucket, primary_score
            ),
            secondary_evidence=secondary_evidence,
            confidence=primary_score,
            grounding_score=self._grounding_score(best),
            answer_source=answer_source,
            is_fallback=answer_source is AnswerSource.EXCERPT_FALLBACK,
            llm_error=llm_error,
            created_at=created_at,
        )
