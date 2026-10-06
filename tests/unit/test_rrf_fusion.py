"""Q5: RRF fusion + decoupling the refusal gate from the batch-relative fused score."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.core.dtos import (
    AskRequest,
    EvidenceCandidate,
    PolicyScope,
    RefusalCode,
    UserContext,
)
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever
from packages.retrieval.hybrid_provider import HybridRetriever


class _StaticRetriever(IVectorRetriever):
    def __init__(self, items: list[EvidenceCandidate]) -> None:
        self._items = items

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        scope: PolicyScope | None = None,
        user: UserContext | None = None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        return self._items


def _cand(
    section_id: UUID,
    text: str,
    score: float,
    *,
    policy_id: UUID,
    version_id: UUID,
    source: str,
    authority: int = 50,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        policy_id=policy_id,
        policy_version_id=version_id,
        section_id=section_id,
        text=text,
        score=score,
        source=source,
        metadata={
            "department_scope": "all",
            "authority_level": authority,
            "is_current": True,
        },
    )


@pytest.fixture(autouse=True)
def _default_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYBRID_VECTOR_WEIGHT", "0.45")
    monkeypatch.setenv("HYBRID_FTS_WEIGHT", "0.35")
    monkeypatch.setenv("HYBRID_AUTHORITY_WEIGHT", "0.15")
    monkeypatch.setenv("HYBRID_RECENCY_WEIGHT", "0.05")
    monkeypatch.setenv("HYBRID_VECTOR_MIN_SIMILARITY", "0.0")
    monkeypatch.setenv("HYBRID_FTS_MIN_SCORE", "0.0")
    monkeypatch.delenv("HYBRID_FUSION", raising=False)


def _pair() -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], UUID, UUID]:
    pid = uuid4()
    s1, s2 = uuid4(), uuid4()
    v1, v2 = uuid4(), uuid4()
    vector = [
        _cand(
            s1, "in both sources", 0.90, policy_id=pid, version_id=v1, source="pgvector"
        ),
        _cand(s2, "vector only", 0.88, policy_id=pid, version_id=v2, source="pgvector"),
    ]
    fts = [
        _cand(
            s1,
            "in both sources",
            0.80,
            policy_id=pid,
            version_id=v1,
            source="pgsql_fts",
        ),
    ]
    return vector, fts, s1, s2


def test_rrf_is_the_default_fusion() -> None:
    vector, fts, _, _ = _pair()
    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert merged
    assert merged[0].metadata["fusion"] == "rrf"


def test_rrf_rewards_appearing_in_both_sources() -> None:
    """The core RRF property: agreement across retrievers beats a single strong hit."""
    vector, fts, both_id, vector_only_id = _pair()
    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert merged[0].section_id == both_id
    assert merged[0].metadata["vector_rank"] == 1
    assert merged[0].metadata["fts_rank"] == 1
    # the vector-only candidate has no FTS rank at all
    others = [c for c in merged if c.section_id == vector_only_id]
    assert others and others[0].metadata["fts_rank"] is None


def test_fused_scores_stay_within_zero_and_one() -> None:
    vector, fts, _, _ = _pair()
    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert all(0.0 <= float(c.score) <= 1.0 for c in merged)


def test_governance_breaks_a_rank_tie_without_clipping() -> None:
    """Two candidates tied on rank must still be ordered by authority.

    Regression guard: summing the governance term saturated past 1.0 and the
    clamp then flattened both candidates to exactly 1.0, losing the ordering.
    """
    pid = uuid4()
    s1, s2 = uuid4(), uuid4()
    v1, v2 = uuid4(), uuid4()

    vector = [
        _cand(
            s1,
            "low authority",
            0.95,
            policy_id=pid,
            version_id=v1,
            source="pgvector",
            authority=20,
        ),
        _cand(
            s2,
            "high authority",
            0.70,
            policy_id=pid,
            version_id=v2,
            source="pgvector",
            authority=100,
        ),
    ]
    fts = [
        _cand(
            s2,
            "high authority",
            0.95,
            policy_id=pid,
            version_id=v2,
            source="pgsql_fts",
            authority=100,
        ),
        _cand(
            s1,
            "low authority",
            0.10,
            policy_id=pid,
            version_id=v1,
            source="pgsql_fts",
            authority=20,
        ),
    ]

    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )
    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert merged[0].text == "high authority"
    assert merged[0].score != merged[1].score, "tie must actually be broken"


def test_linear_fusion_remains_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the old behaviour reachable so the eval harness can measure the delta."""
    monkeypatch.setenv("HYBRID_FUSION", "linear")
    vector, fts, _, _ = _pair()
    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert merged[0].metadata.get("fusion") != "rrf"
    assert "vector_score" in merged[0].metadata


# --- the decoupled refusal gate ----------------------------------------


def test_true_similarity_is_carried_for_the_refusal_gate() -> None:
    """Q5: the gate needs an absolute measure, not the batch-relative fused score."""
    vector, fts, both_id, _ = _pair()
    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever(vector),
        fts_retriever=_StaticRetriever(fts),
    )

    merged = retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)
    top = next(c for c in merged if c.section_id == both_id)

    assert top.metadata["vector_similarity"] == 0.90
    assert top.metadata["fts_rank_score"] == 0.80


def test_gate_uses_similarity_not_the_inflated_fused_score() -> None:
    """A weak cosine must refuse even when fusion pushed the score near 1.0."""
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Only loosely related.",
        score=0.99,  # batch-relative fused score, inflated
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "is_current": True,
            "retriever": "hybrid",
            "fusion": "rrf",
            "vector_similarity": 0.31,  # the truth
        },
    )

    tid = uuid4()
    request = AskRequest(
        tenant_id=tid,
        question="What is the deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal is not None
    assert response.grounding_score == pytest.approx(0.31)
    assert response.refusal.best_score == pytest.approx(0.31)


def test_strong_similarity_answers_despite_modest_fused_score() -> None:
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Submit within 30 days.",
        score=0.41,
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "is_current": True,
            "retriever": "hybrid",
            "fusion": "rrf",
            "vector_similarity": 0.88,
        },
    )

    tid = uuid4()
    request = AskRequest(
        tenant_id=tid,
        question="What is the deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal_reason is None
    assert response.grounding_score == pytest.approx(0.88)
    # confidence stays the fused relevance heuristic, distinct from grounding
    assert response.confidence == pytest.approx(0.41)


def test_backends_without_similarity_fall_back_to_score() -> None:
    """pgvector/cosmos put a true cosine straight on score."""
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Submit within 30 days.",
        score=0.77,
        source="pgvector",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "is_current": True,
        },
    )

    tid = uuid4()
    request = AskRequest(
        tenant_id=tid,
        question="What is the deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal_reason is None
    assert response.grounding_score == pytest.approx(0.77)


def test_lexical_only_match_is_not_gated_against_a_cosine_threshold() -> None:
    """Q5 regression: an FTS-only candidate has no similarity to compare.

    Found live: "What does SC-7 require?" retrieved the right section by full
    text, but with no vector_similarity the gate fell back to the fused RRF
    score (~0.35) and compared it to the 0.5 cosine threshold, refusing a
    correct answer — the same cross-backend mis-calibration Q5 removes.
    """
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="SC-7 Boundary Protection: monitor and control communications.",
        score=0.35,  # rank-derived, NOT a similarity
        source="hybrid",
        metadata={
            "department_scope": "all",
            "is_current": True,
            "retriever": "hybrid",
            "fusion": "rrf",
            "fts_rank": 1,
            "vector_rank": None,
            # no vector_similarity: FTS surfaced this, the vector leg did not
        },
    )

    tid = uuid4()
    request = AskRequest(tenant_id=tid, question="What does SC-7 require?")
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal_reason is None, "lexical-only evidence must not be refused"
    assert response.grounding_score is None, "no absolute measure exists to report"
    assert response.confidence == pytest.approx(0.35)


def test_weak_cosine_is_still_gated() -> None:
    """The fix must not disable the gate where a real similarity exists."""
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Loosely related text.",
        score=0.95,
        source="hybrid",
        metadata={
            "department_scope": "all",
            "is_current": True,
            "retriever": "hybrid",
            "fusion": "rrf",
            "vector_similarity": 0.28,
        },
    )

    tid = uuid4()
    request = AskRequest(tenant_id=tid, question="What is the deadline?")
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD
    assert response.grounding_score == pytest.approx(0.28)
