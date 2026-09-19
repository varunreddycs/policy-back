"""Hosted cross-encoder rerankers: Cohere Rerank and Voyage rerank (Q4).

Both expose the same shape — POST a query plus documents, receive scored
indices back — so they share a base. Neither is configured by default; without
an API key the factory hands back a passthrough instead, so merging this costs
nothing at runtime.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from packages.core.dtos import EvidenceCandidate
from packages.reranking.base import IReranker

logger = logging.getLogger(__name__)

# Text sent per document. Cross-encoders truncate anyway and long documents
# cost tokens; the retrieval chunks are ~4000 chars, so this trims to the part
# most likely to carry the answer.
_MAX_DOC_CHARS = 2000


class _HttpReranker(IReranker):
    """Shared POST-scored-indices reranker behaviour."""

    provider = "http"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str,
        timeout_seconds: int = 30,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._url = url
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, query: str, documents: list[str], top_k: int) -> dict[str, Any]:
        return {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_k,
        }

    @staticmethod
    def _parse_ranking(payload: dict[str, Any]) -> list[tuple[int, float]]:
        """Both APIs return results[] with index + relevance_score."""
        rows = payload.get("results") or payload.get("data") or []
        ranked: list[tuple[int, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = row.get("index")
            score = row.get("relevance_score", row.get("score"))
            if isinstance(index, int) and isinstance(score, (int, float)):
                ranked.append((index, float(score)))
        return ranked

    def rerank(
        self,
        *,
        query: str,
        candidates: list[EvidenceCandidate],
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        limit = max(1, int(top_k))
        if len(candidates) <= 1:
            return candidates[:limit]

        documents = [(c.text or "")[:_MAX_DOC_CHARS] for c in candidates]

        try:
            resp = requests.post(
                self._url,
                json=self._body(query, documents, limit),
                headers=self._headers(),
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "rerank.request.failed",
                    extra={
                        "provider": self.provider,
                        "status": resp.status_code,
                        "body": resp.text[:200],
                    },
                )
                return candidates[:limit]
            ranked = self._parse_ranking(resp.json())
        except (requests.RequestException, ValueError) as exc:
            # Graceful passthrough: a reranker outage must not fail retrieval.
            logger.warning(
                "rerank.request.error",
                extra={"provider": self.provider, "error": str(exc)},
            )
            return candidates[:limit]

        if not ranked:
            logger.warning("rerank.empty_ranking", extra={"provider": self.provider})
            return candidates[:limit]

        reordered: list[EvidenceCandidate] = []
        for index, score in ranked:
            if not 0 <= index < len(candidates):
                continue
            candidate = candidates[index]
            md = dict(candidate.metadata or {})
            md["rerank_score"] = score
            md["rerank_provider"] = self.provider
            md["pre_rerank_score"] = float(candidate.score or 0.0)
            md["pre_rerank_position"] = index
            reordered.append(candidate.model_copy(update={"metadata": md}))

        return reordered[:limit] if reordered else candidates[:limit]


class CohereReranker(_HttpReranker):
    """Cohere Rerank (e.g. rerank-v3.5)."""

    provider = "cohere"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("COHERE_API_KEY", ""),
            model=model or os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5"),
            url=os.getenv("COHERE_RERANK_URL", "https://api.cohere.com/v2/rerank"),
            timeout_seconds=timeout_seconds or 30,
        )


class VoyageReranker(_HttpReranker):
    """Voyage AI rerank (e.g. rerank-2.5)."""

    provider = "voyage"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("VOYAGE_API_KEY", ""),
            model=model or os.getenv("VOYAGE_RERANK_MODEL", "rerank-2.5"),
            url=os.getenv("VOYAGE_RERANK_URL", "https://api.voyageai.com/v1/rerank"),
            timeout_seconds=timeout_seconds or 30,
        )
