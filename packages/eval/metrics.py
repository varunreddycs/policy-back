"""Reference-free eval metrics for the /v1/ask contract (Q3).

The committed question set carries no ground-truth answers, so these metrics are
deliberately deterministic and reference-free: they measure what retrieval and
the answer contract *did*, not whether prose was "good". That makes them safe to
run in CI without an LLM judge, and sensitive to exactly the changes Q3 needs to
catch — a different RETRIEVER_BACKEND, retuned fusion weights, a moved refusal
threshold, or an edited strict-citation prompt all move these numbers.

LLM-judged metrics (RAGAS faithfulness / context precision-recall, DeepEval)
belong on top of this once reference answers exist; see ``scripts/run_eval.py``.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

# Matches the citation handles the answer contract emits, e.g.
# [policy_version_id=... section_id=...]
_CITATION_RE = re.compile(r"\[policy_version_id=[^\]]+\]")

# NIST-style control identifiers: AC-2, IA-5(1), SC-7(3).
_CONTROL_ID_RE = re.compile(r"\b[A-Z]{2}-\d+(?:\(\d+\))?")


@dataclass(slots=True)
class QuestionResult:
    """Per-question scores, persisted so regressions can be attributed."""

    question_id: str
    suite: str
    category: str
    variant: str
    question: str

    status: int = 200
    answered: bool = False
    refused: bool = False
    refusal_code: str | None = None
    is_fallback: bool = False
    answer_source: str | None = None

    citation_count: int = 0
    citation_item_count: int = 0
    evidence_count: int = 0
    secondary_count: int = 0
    answer_chars: int = 0

    confidence: float | None = None
    top_score: float | None = None
    selected_bucket: str | None = None

    fts_candidates: int = 0
    vector_candidates: int = 0
    merged_candidates: int = 0

    answer_cites_evidence: bool = False
    control_ids_in_answer: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalMetrics:
    """Aggregate view across the whole question set."""

    total: int = 0
    answered: int = 0
    refused: int = 0
    errors: int = 0
    fallbacks: int = 0

    answer_rate: float = 0.0
    refusal_rate: float = 0.0
    fallback_rate: float = 0.0
    citation_coverage: float = 0.0
    grounded_citation_rate: float = 0.0

    mean_citations: float = 0.0
    mean_evidence: float = 0.0
    mean_confidence: float = 0.0
    median_confidence: float = 0.0

    mean_fts_candidates: float = 0.0
    mean_vector_candidates: float = 0.0

    refusal_codes: dict[str, int] = field(default_factory=dict)
    buckets: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round(value: float, places: int = 4) -> float:
    return round(float(value), places)


def score_response(
    *,
    question_id: str,
    suite: str,
    category: str,
    variant: str,
    question: str,
    status: int,
    response: dict[str, Any],
) -> QuestionResult:
    """Score one /v1/ask response into a flat, diffable record."""
    result = QuestionResult(
        question_id=question_id,
        suite=suite,
        category=category,
        variant=variant,
        question=question,
        status=status,
    )

    if status != 200 or not isinstance(response, dict):
        return result

    answer = str(response.get("answer") or "")
    refusal_reason = response.get("refusal_reason")

    result.answer_chars = len(answer)
    result.refused = bool(refusal_reason)
    result.refusal_code = str(refusal_reason) if refusal_reason else None
    result.answered = not result.refused and bool(answer.strip())
    result.is_fallback = bool(response.get("is_fallback"))
    result.answer_source = response.get("answer_source")

    citations = response.get("citations") or []
    citation_items = response.get("citation_items") or []
    evidence = response.get("evidence") or []
    secondary = response.get("secondary_evidence") or []

    result.citation_count = len(citations) if isinstance(citations, list) else 0
    result.citation_item_count = (
        len(citation_items) if isinstance(citation_items, list) else 0
    )
    result.evidence_count = len(evidence) if isinstance(evidence, list) else 0
    result.secondary_count = len(secondary) if isinstance(secondary, list) else 0

    confidence = response.get("confidence")
    result.confidence = (
        float(confidence) if isinstance(confidence, (int, float)) else None
    )

    decision = response.get("decision")
    if isinstance(decision, dict):
        bucket = decision.get("selected_bucket")
        result.selected_bucket = str(bucket) if bucket else None

    log = response.get("retrieval_log")
    if isinstance(log, dict):
        result.fts_candidates = int(log.get("fts_candidates") or 0)
        result.vector_candidates = int(log.get("vector_candidates") or 0)
        result.merged_candidates = int(log.get("merged") or 0)
        top = log.get("primary_score")
        result.top_score = float(top) if isinstance(top, (int, float)) else None

    # Groundedness proxy: does the answer text actually carry a citation handle
    # pointing at a version we retrieved? Catches a prompt edit that drops the
    # citation format without needing an LLM judge.
    handles = _CITATION_RE.findall(answer)
    if handles and isinstance(evidence, list):
        retrieved_versions = {
            str((item or {}).get("policy_version_id"))
            for item in evidence
            if isinstance(item, dict)
        }
        result.answer_cites_evidence = any(
            version and version in handle
            for handle in handles
            for version in retrieved_versions
        )

    result.control_ids_in_answer = sorted(set(_CONTROL_ID_RE.findall(answer)))
    return result


def aggregate(results: list[QuestionResult]) -> EvalMetrics:
    """Roll per-question results into the comparable summary."""
    metrics = EvalMetrics(total=len(results))
    if not results:
        return metrics

    metrics.errors = sum(1 for r in results if r.status != 200)
    metrics.answered = sum(1 for r in results if r.answered)
    metrics.refused = sum(1 for r in results if r.refused)
    metrics.fallbacks = sum(1 for r in results if r.is_fallback)

    total = float(len(results))
    metrics.answer_rate = _round(metrics.answered / total)
    metrics.refusal_rate = _round(metrics.refused / total)
    metrics.fallback_rate = _round(metrics.fallbacks / total)

    answered = [r for r in results if r.answered]
    if answered:
        with_citations = sum(1 for r in answered if r.citation_count > 0)
        grounded = sum(1 for r in answered if r.answer_cites_evidence)
        metrics.citation_coverage = _round(with_citations / len(answered))
        metrics.grounded_citation_rate = _round(grounded / len(answered))
        metrics.mean_citations = _round(
            statistics.fmean(r.citation_count for r in answered), 3
        )
        metrics.mean_evidence = _round(
            statistics.fmean(r.evidence_count for r in answered), 3
        )

    confidences = [r.confidence for r in results if r.confidence is not None]
    if confidences:
        metrics.mean_confidence = _round(statistics.fmean(confidences))
        metrics.median_confidence = _round(statistics.median(confidences))

    metrics.mean_fts_candidates = _round(
        statistics.fmean(r.fts_candidates for r in results), 3
    )
    metrics.mean_vector_candidates = _round(
        statistics.fmean(r.vector_candidates for r in results), 3
    )

    for r in results:
        if r.refusal_code:
            metrics.refusal_codes[r.refusal_code] = (
                metrics.refusal_codes.get(r.refusal_code, 0) + 1
            )
        if r.selected_bucket:
            metrics.buckets[r.selected_bucket] = (
                metrics.buckets.get(r.selected_bucket, 0) + 1
            )

    return metrics
