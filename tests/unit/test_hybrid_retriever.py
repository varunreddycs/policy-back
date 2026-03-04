from __future__ import annotations

from uuid import uuid4

from packages.core.dtos import EvidenceCandidate
from packages.retrieval.hybrid_provider import HybridRetriever


class _StaticRetriever:
    def __init__(self, items):
        self._items = items

    def retrieve(self, **kwargs):
        return self._items


def test_hybrid_retriever_merges_fts_and_vector_results() -> None:
    policy_id = uuid4()
    version_id = uuid4()
    shared_section = uuid4()
    fts_only_section = uuid4()

    vector_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=shared_section,
            text="Vector hit",
            score=0.9,
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 60},
        )
    ]

    fts_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=shared_section,
            text="FTS shared hit",
            score=0.4,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 60},
        ),
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=fts_only_section,
            text="FTS-only hit",
            score=0.7,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 50},
        ),
    ]

    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector_results),
        fts_retriever=_StaticRetriever(fts_results),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="appeal deadline", top_k=10)

    assert len(merged) == 2
    sources = {item.metadata.get("retriever_source") for item in merged}
    assert "pgvector" in sources
    assert "pgsql_fts" in sources
    assert all(item.source == "hybrid" for item in merged)
