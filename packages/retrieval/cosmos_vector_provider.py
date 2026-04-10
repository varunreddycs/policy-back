"""Cosmos DB NoSQL vector search retrieval provider.

Uses the DiskANN vector index on the `embeddings` container for semantic
search, with optional keyword pre-filtering.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, List, Optional

from packages.core.dtos import EvidenceCandidate

try:
    from packages.core.dtos import PolicyScope, UserContext
except Exception:
    PolicyScope = object  # type: ignore
    UserContext = object  # type: ignore

from packages.retrieval.base import IVectorRetriever


logger = logging.getLogger(__name__)


class CosmosVectorRetriever(IVectorRetriever):
    """Retrieves evidence candidates using Cosmos DB NoSQL vector search (DiskANN).

    Requires the `embeddings` container to have a vector index on `/embedding`
    with `distanceFunction: cosine` and `dimensions: 3072`.
    """

    def __init__(
        self,
        *,
        embeddings_container: Any,
        policies_container: Any,
        embed_fn: Any = None,
        default_top_k: int = 20,
    ) -> None:
        self._embeddings = embeddings_container
        self._policies = policies_container
        self._embed_fn = embed_fn
        self._default_top_k = default_top_k

    def retrieve(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str,
        scope: "PolicyScope | None" = None,
        user: "UserContext | None" = None,
        top_k: int = 10,
    ) -> List[EvidenceCandidate]:
        if not query or not query.strip():
            return []

        top_k = min(top_k, self._default_top_k)

        # Generate query embedding
        query_vector = self._get_query_embedding(query)
        if query_vector is None:
            logger.warning("cosmos_vector.no_embedding_available")
            return []

        # Build the vector search query
        # Cosmos DB NoSQL vector search syntax
        cosmos_query = (
            "SELECT TOP @topK c.id, c.tenant_id, c.policy_version_id, c.policy_section_id, "
            "c.embedding_model, c.authority_level, c.department_scope, c.policy_type, "
            "c.effective_date, "
            "VectorDistance(c.embedding, @queryVector) AS similarity_score "
            "FROM c "
            "WHERE c.tenant_id = @tenantId "
            "ORDER BY VectorDistance(c.embedding, @queryVector)"
        )
        params = [
            {"name": "@topK", "value": top_k},
            {"name": "@tenantId", "value": str(tenant_id)},
            {"name": "@queryVector", "value": query_vector},
        ]

        try:
            results = list(self._embeddings.query_items(
                query=cosmos_query,
                parameters=params,
                partition_key=str(tenant_id),
            ))
        except Exception:
            logger.exception("cosmos_vector.query_failed")
            return []

        # Convert to EvidenceCandidate by looking up section text
        candidates = []
        for row in results:
            section_data = self._get_section_data(
                tenant_id=tenant_id,
                section_id=row["policy_section_id"],
            )
            if section_data is None:
                continue

            similarity = row.get("similarity_score", 0.0)

            candidates.append(EvidenceCandidate(
                section_id=uuid.UUID(row["policy_section_id"]),
                policy_id=section_data["policy_id"],
                policy_version_id=uuid.UUID(row["policy_version_id"]),
                policy_name=section_data.get("policy_name", ""),
                section_index=section_data.get("section_index", 0),
                section_title=section_data.get("title", ""),
                text=section_data.get("text", ""),
                score=float(similarity),
                source="cosmos_vector",
                authority_level=row.get("authority_level", 0),
                department_scope=row.get("department_scope", "all"),
                is_current=section_data.get("is_current", False),
                effective_date=section_data.get("effective_date"),
            ))

        return candidates

    def _get_query_embedding(self, query: str) -> Optional[List[float]]:
        """Generate embedding for the query text."""
        if self._embed_fn is not None:
            return self._embed_fn(query)

        # Try using the embeddings package
        try:
            from packages.embeddings.embed import embed_texts
            results = embed_texts([query])
            return results[0] if results else None
        except Exception:
            logger.warning("cosmos_vector.embed_fn_unavailable")
            return None

    def _get_section_data(self, *, tenant_id: uuid.UUID, section_id: str) -> Optional[dict]:
        """Look up section text and parent policy info from the policies container."""
        query = "SELECT * FROM c WHERE c.tenant_id = @tid"
        params = [{"name": "@tid", "value": str(tenant_id)}]
        for doc in self._policies.query_items(query=query, parameters=params, partition_key=str(tenant_id)):
            for v in doc.get("versions", []):
                for s in v.get("sections", []):
                    if s["id"] == str(section_id):
                        return {
                            "policy_id": uuid.UUID(doc["id"]),
                            "policy_name": doc["name"],
                            "section_index": s.get("section_index", 0),
                            "title": s.get("title", ""),
                            "text": s.get("text", ""),
                            "is_current": v.get("is_current", False),
                            "effective_date": v.get("effective_date"),
                        }
        return None
