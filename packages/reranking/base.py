"""Reranker interface (Q4).

Mirrors ``IVectorRetriever``: an ABC plus a factory switch, so a reranking
backend can be swapped by config with graceful passthrough when unconfigured.

Ordering contract
-----------------
A reranker refines *relevance* ordering only. It never encodes the
department -> org_wide -> cross_dept precedence, which is a compliance business
rule owned by ``PolicyRanker`` and applied after bucketing in ``AnswerService``.
Reranking runs upstream of that, so a cross-department section can never be
promoted past a departmental one by a better relevance score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.dtos import EvidenceCandidate


class IReranker(ABC):
    """Reorders retrieved candidates by query relevance."""

    @abstractmethod
    def rerank(
        self,
        *,
        query: str,
        candidates: list[EvidenceCandidate],
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        """Return candidates reordered by relevance, truncated to ``top_k``.

        Implementations must degrade gracefully: on any backend failure return
        the input order rather than raising, so retrieval never hard-fails
        because a reranker was unavailable.
        """
        raise NotImplementedError


class PassthroughReranker(IReranker):
    """No-op reranker — preserves fused order. The default when unconfigured."""

    def rerank(
        self,
        *,
        query: str,
        candidates: list[EvidenceCandidate],
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        return candidates[: max(1, int(top_k))]
