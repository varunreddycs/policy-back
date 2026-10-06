"""Retriever decorator that inserts the rerank stage (Q4).

Sits between the fused retriever and ``AnswerService``, so the pipeline becomes

    hybrid fusion (top 40) -> rerank (top 10) -> bucket -> PolicyRanker

Reranking therefore only ever refines *which* candidates and in what relevance
order they reach bucketing. Department precedence is applied afterwards by
``AnswerService._bucket_candidates`` plus ``PolicyRanker``, so a better
relevance score can never promote a cross-department section over a
departmental one.
"""

from __future__ import annotations

import logging

from packages.core.dtos import EvidenceCandidate
from packages.reranking.base import IReranker
from packages.retrieval.base import IVectorRetriever

logger = logging.getLogger(__name__)


class RerankingRetriever(IVectorRetriever):
    """Wraps a retriever and reranks its results before they are returned."""

    def __init__(
        self,
        *,
        retriever: IVectorRetriever,
        reranker: IReranker,
        rerank_top_k: int = 10,
        fetch_multiplier: int = 4,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._rerank_top_k = max(1, int(rerank_top_k))
        self._fetch_multiplier = max(1, int(fetch_multiplier))

    def retrieve(
        self,
        *,
        tenant_id,
        query: str,
        scope=None,
        user=None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        # Rerankers earn their keep by seeing a wider pool than they return, so
        # fetch deeper than the caller asked for, then narrow.
        fetch_k = max(int(top_k), self._rerank_top_k * self._fetch_multiplier)

        candidates = self._retriever.retrieve(
            tenant_id=tenant_id,
            query=query,
            scope=scope,
            user=user,
            top_k=fetch_k,
        )
        if not candidates:
            return candidates

        keep = min(max(int(top_k), self._rerank_top_k), len(candidates))
        reranked = self._reranker.rerank(query=query, candidates=candidates, top_k=keep)

        # Preserve the retriever debug counters the answer service reads off
        # candidate[0]; a reranker that reorders would otherwise hide them.
        source_meta = candidates[0].metadata or {}
        debug_keys = {
            key: value
            for key, value in source_meta.items()
            if key.startswith("hybrid_")
        }
        if debug_keys and reranked:
            debug_keys["rerank_input_candidates"] = len(candidates)
            enriched: list[EvidenceCandidate] = []
            for item in reranked:
                md = dict(item.metadata or {})
                md.update(debug_keys)
                enriched.append(item.model_copy(update={"metadata": md}))
            return enriched

        return reranked
