"""Cosmos DB NoSQL vector search retrieval provider.

Uses the DiskANN vector index on the `embeddings` container for semantic
search. Embedding documents are denormalized (they carry the section text and
policy/section metadata needed to build a candidate), so retrieval is a single
vector query with no secondary lookups.

`VectorDistance` with a cosine distance function returns the cosine similarity
directly (higher = more similar, ~[0, 1] for normalized embeddings), and
`ORDER BY VectorDistance(...)` returns most-similar-first. The returned value is
used as the candidate score as-is, so the downstream refusal threshold operates
on a true similarity.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, List, Optional

from packages.core.dtos import EvidenceCandidate

# Matches NIST control identifiers in a query, e.g. "AC-2", "ac-2", "IA-5(1)".
_CONTROL_ID_RE = re.compile(r"\b([A-Za-z]{2})-(\d+)(\(\d+\))?\b")
# How much to boost a candidate whose section_path exactly matches a control
# named in the query — large enough to surface the named control to the top.
_EXACT_ID_BOOST = 0.4


def _query_control_ids(query: str) -> set[str]:
    return {f"{m.group(1).upper()}-{int(m.group(2))}{m.group(3) or ''}" for m in _CONTROL_ID_RE.finditer(query)}

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
        policies_container: Any = None,
        sections_container: Any = None,
        embed_fn: Any = None,
        default_top_k: int = 20,
    ) -> None:
        self._embeddings = embeddings_container
        self._policies = policies_container
        self._sections = sections_container
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

        query_vector = self._get_query_embedding(query)
        if query_vector is None:
            logger.warning("cosmos_vector.no_embedding_available")
            return []

        cosmos_query = (
            "SELECT TOP @topK c.policy_id, c.policy_version_id, c.policy_section_id, "
            "c.policy_name, c.section_title, c.section_path, c.section_index, c.text, "
            "c.authority_level, c.department_scope, c.policy_type, c.is_current, "
            "c.effective_date, c.public_url, "
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
            results = list(
                self._embeddings.query_items(
                    query=cosmos_query,
                    parameters=params,
                    partition_key=str(tenant_id),
                )
            )
        except Exception:
            logger.exception("cosmos_vector.query_failed")
            return []

        candidates: List[EvidenceCandidate] = []
        for row in results:
            section_id = row.get("policy_section_id")
            policy_id = row.get("policy_id")
            policy_version_id = row.get("policy_version_id")
            if not (section_id and policy_id and policy_version_id):
                continue

            text = row.get("text")
            if not text:
                # Fallback for non-denormalized embeddings: look up section text.
                text = self._lookup_section_text(tenant_id=tenant_id, section_id=section_id)
            if not text:
                continue

            candidates.append(
                EvidenceCandidate(
                    policy_id=uuid.UUID(str(policy_id)),
                    policy_version_id=uuid.UUID(str(policy_version_id)),
                    section_id=uuid.UUID(str(section_id)),
                    text=text,
                    score=float(row.get("similarity_score") or 0.0),
                    source="cosmos_vector",
                    metadata={
                        "policy_name": row.get("policy_name"),
                        "title": row.get("section_title"),
                        "section_path": row.get("section_path"),
                        "section_index": row.get("section_index"),
                        "authority_level": row.get("authority_level") or 0,
                        "department_scope": row.get("department_scope") or "all",
                        "policy_type": row.get("policy_type"),
                        "is_current": bool(row.get("is_current", True)),
                        "effective_date": row.get("effective_date"),
                        "public_url": row.get("public_url"),
                    },
                )
            )

        # Lexical boost: if the query names specific controls (e.g. "AC-2"),
        # surface the exact control above semantically-near neighbours so its
        # text is in the evidence the LLM sees.
        named = _query_control_ids(query)
        if named:
            for cand in candidates:
                path = (cand.metadata or {}).get("section_path")
                if path and str(path).upper() in named:
                    cand.score = min(0.99, float(cand.score) + _EXACT_ID_BOOST)
            candidates.sort(key=lambda c: c.score, reverse=True)

        return candidates

    def _get_query_embedding(self, query: str) -> Optional[List[float]]:
        if self._embed_fn is not None:
            return self._embed_fn(query)
        try:
            from packages.embeddings import embed_texts

            results = embed_texts([query])
            return results[0] if results else None
        except Exception:
            logger.exception("cosmos_vector.embed_fn_unavailable")
            return None

    def _lookup_section_text(self, *, tenant_id: uuid.UUID, section_id: str) -> Optional[str]:
        """Fallback section-text lookup from the standalone sections container."""
        if self._sections is None:
            return None
        try:
            rows = list(
                self._sections.query_items(
                    query="SELECT c.text FROM c WHERE c.id = @sid AND c.tenant_id = @tid",
                    parameters=[
                        {"name": "@sid", "value": str(section_id)},
                        {"name": "@tid", "value": str(tenant_id)},
                    ],
                    partition_key=str(tenant_id),
                )
            )
        except Exception:
            logger.exception("cosmos_vector.section_lookup_failed")
            return None
        return rows[0].get("text") if rows else None
