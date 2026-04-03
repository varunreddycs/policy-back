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

    merged = retriever.retrieve(tenant_id=uuid4(), query="submission deadline", top_k=10)

    assert len(merged) == 2
    assert all(item.source == "hybrid" for item in merged)
    assert all("final_score" in (item.metadata or {}) for item in merged)


def test_hybrid_retriever_filters_low_similarity_and_low_fts(monkeypatch) -> None:
    policy_id = uuid4()
    version_id = uuid4()

    vector_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=uuid4(),
            text="low vector",
            score=0.64,
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 10},
        ),
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=uuid4(),
            text="good vector",
            score=0.9,
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 80},
        ),
    ]
    fts_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=uuid4(),
            text="low fts",
            score=0.01,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 10},
        ),
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=uuid4(),
            text="good fts",
            score=0.3,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 40},
        ),
    ]

    monkeypatch.setenv("HYBRID_VECTOR_MIN_SIMILARITY", "0.65")
    monkeypatch.setenv("HYBRID_FTS_MIN_SCORE", "0.05")

    retriever = HybridRetriever(vector_retriever=_StaticRetriever(vector_results), fts_retriever=_StaticRetriever(fts_results))
    merged = retriever.retrieve(tenant_id=uuid4(), query="submission", top_k=10)

    texts = {item.text for item in merged}
    assert "low vector" not in texts
    assert "low fts" not in texts
    assert "good vector" in texts
    assert "good fts" in texts


def test_hybrid_retriever_caps_three_candidates_per_policy_version() -> None:
    policy_id = uuid4()
    version_id = uuid4()

    vector_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=uuid4(),
            text=f"vector-{i}",
            score=0.95 - (i * 0.02),
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 50 + i},
        )
        for i in range(5)
    ]

    retriever = HybridRetriever(vector_retriever=_StaticRetriever(vector_results), fts_retriever=_StaticRetriever([]))
    merged = retriever.retrieve(tenant_id=uuid4(), query="submission", top_k=15)

    assert len(merged) == 3
    assert len({str(item.policy_version_id) for item in merged}) == 1


def test_hybrid_retriever_final_score_orders_by_fused_components(monkeypatch) -> None:
    policy_id = uuid4()
    version_id = uuid4()

    s1 = uuid4()
    s2 = uuid4()

    # s1 has stronger vector score; s2 has stronger fts + authority/recency.
    vector_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=s1,
            text="vector strong",
            score=0.95,
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 20, "effective_date": "2025-01-01"},
        ),
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=s2,
            text="fts strong",
            score=0.7,
            source="pgvector",
            metadata={"department_scope": "all", "authority_level": 100, "effective_date": "2026-01-01"},
        ),
    ]
    fts_results = [
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=s1,
            text="vector strong",
            score=0.1,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 20, "effective_date": "2025-01-01"},
        ),
        EvidenceCandidate(
            policy_id=policy_id,
            policy_version_id=version_id,
            section_id=s2,
            text="fts strong",
            score=0.95,
            source="pgsql_fts",
            metadata={"department_scope": "all", "authority_level": 100, "effective_date": "2026-01-01"},
        ),
    ]

    monkeypatch.setenv("HYBRID_VECTOR_WEIGHT", "0.45")
    monkeypatch.setenv("HYBRID_FTS_WEIGHT", "0.35")
    monkeypatch.setenv("HYBRID_AUTHORITY_WEIGHT", "0.15")
    monkeypatch.setenv("HYBRID_RECENCY_WEIGHT", "0.05")

    retriever = HybridRetriever(vector_retriever=_StaticRetriever(vector_results), fts_retriever=_StaticRetriever(fts_results))
    merged = retriever.retrieve(tenant_id=uuid4(), query="submission", top_k=10)

    assert len(merged) == 2
    assert merged[0].text == "fts strong"

