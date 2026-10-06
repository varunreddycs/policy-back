"""Cross-encoder reranking stage (Q4).

Refines relevance ordering within the retrieved pool before bucketing. It never
overrides the department -> org_wide -> cross_dept precedence, which stays with
``PolicyRanker``; see ``packages/reranking/base.py`` for the ordering contract.
"""

from packages.reranking.base import IReranker, PassthroughReranker
from packages.reranking.factory import build_reranker, rerank_top_k
from packages.reranking.reranking_retriever import RerankingRetriever

__all__ = [
    "IReranker",
    "PassthroughReranker",
    "RerankingRetriever",
    "build_reranker",
    "rerank_top_k",
]
