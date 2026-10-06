"""RERANKER_BACKEND switch (Q4), mirroring packages/retrieval/factory.py."""

from __future__ import annotations

import logging
import os

from packages.reranking.base import IReranker, PassthroughReranker

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def rerank_top_k() -> int:
    """How many candidates survive reranking and reach the bucket ranker."""
    return max(1, _env_int("RERANK_TOP_K", 10))


def build_reranker() -> IReranker:
    """Build the configured reranker, falling back to passthrough.

    Unconfigured is the default and is not an error: a missing API key means
    the stage is simply a no-op, so the ranking pipeline behaves exactly as it
    did before this backend existed.
    """
    backend = os.getenv("RERANKER_BACKEND", "none").strip().lower()

    if backend in {"", "none", "off", "passthrough"}:
        return PassthroughReranker()

    if backend == "cohere":
        from packages.reranking.http_rerankers import CohereReranker

        if not os.getenv("COHERE_API_KEY"):
            logger.warning("rerank.backend.unconfigured", extra={"backend": backend})
            return PassthroughReranker()
        return CohereReranker()

    if backend == "voyage":
        from packages.reranking.http_rerankers import VoyageReranker

        if not os.getenv("VOYAGE_API_KEY"):
            logger.warning("rerank.backend.unconfigured", extra={"backend": backend})
            return PassthroughReranker()
        return VoyageReranker()

    if backend in {"azure", "azure_llm"}:
        from packages.reranking.azure_llm_reranker import AzureLlmReranker

        reranker = AzureLlmReranker()
        if not reranker.available:
            logger.warning("rerank.backend.unconfigured", extra={"backend": backend})
            return PassthroughReranker()
        return reranker

    logger.warning("rerank.backend.unknown", extra={"backend": backend})
    return PassthroughReranker()
