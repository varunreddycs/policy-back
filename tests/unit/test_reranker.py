"""Q4: cross-encoder rerank stage.

The load-bearing test here is that reranking refines relevance WITHIN the
department buckets and never overrides the department -> org_wide -> cross_dept
precedence, which is a compliance business rule.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
import requests

from packages.core.dtos import (
    AskRequest,
    EvidenceCandidate,
    PolicyScope,
    UserContext,
)
from packages.llm.client import LlmClient, LlmError
from packages.rag.answer_service import AnswerService
from packages.reranking.azure_llm_reranker import AzureLlmReranker
from packages.reranking.base import IReranker, PassthroughReranker
from packages.reranking.factory import build_reranker
from packages.reranking.http_rerankers import CohereReranker, VoyageReranker
from packages.reranking.reranking_retriever import RerankingRetriever
from packages.retrieval.base import IVectorRetriever


class _StaticRetriever(IVectorRetriever):
    def __init__(self, items: list[EvidenceCandidate]) -> None:
        self._items = items
        self.last_top_k: int | None = None

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        scope: PolicyScope | None = None,
        user: UserContext | None = None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        self.last_top_k = top_k
        return self._items


class _ReversingReranker(IReranker):
    """Deterministic stand-in: reverses the input order."""

    def rerank(
        self, *, query: str, candidates: list[EvidenceCandidate], top_k: int = 10
    ) -> list[EvidenceCandidate]:
        return list(reversed(candidates))[: max(1, top_k)]


def _candidate(
    text: str,
    score: float,
    *,
    dept: str = "operations",
    user_dept: str = "operations",
    policy_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvidenceCandidate:
    md: dict[str, Any] = {
        "department_scope": dept,
        "user_department": user_dept,
        "is_current": True,
    }
    md.update(metadata or {})
    return EvidenceCandidate(
        policy_id=policy_id or uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text=text,
        score=score,
        source="hybrid",
        metadata=md,
    )


# --- the compliance constraint -----------------------------------------


def test_rerank_never_promotes_cross_dept_over_departmental() -> None:
    """Q4's central rule: rerank refines within-bucket relevance only.

    A reranker that puts a cross-department section first must still lose to
    the departmental bucket, because bucketing runs after reranking.
    """
    ops = _candidate("Operations rule: submit within 30 days.", 0.70, dept="operations")
    jfs = _candidate("JFS rule: submit within 45 days.", 0.95, dept="jfs")

    # The reranker reverses, so JFS (the cross-dept section) lands first.
    retriever = RerankingRetriever(
        retriever=_StaticRetriever([ops, jfs]),
        reranker=_ReversingReranker(),
        rerank_top_k=10,
    )

    tid = uuid4()
    request = AskRequest(
        tenant_id=tid,
        question="What is the submission deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=retriever).ask(request)

    assert response.decision is not None
    assert response.decision.selected_bucket == "department_specific"
    # The operations section still wins despite ranking last after rerank.
    assert "30 days" in response.answer
    assert response.citation_items[0].section_id == ops.section_id


def test_rerank_reorders_within_the_same_bucket() -> None:
    """Within one department, rerank order decides the winner."""
    weak_first = _candidate("Mentions deadlines vaguely.", 0.90, dept="operations")
    strong_second = _candidate(
        "Submit within 30 days of the event.", 0.85, dept="operations"
    )

    retriever = RerankingRetriever(
        retriever=_StaticRetriever([weak_first, strong_second]),
        reranker=_ReversingReranker(),
        rerank_top_k=10,
    )

    candidates = retriever.retrieve(tenant_id=uuid4(), query="deadline?")

    assert candidates[0].section_id == strong_second.section_id


# --- the wrapper --------------------------------------------------------


def test_reranking_retriever_fetches_a_wider_pool_than_it_returns() -> None:
    inner = _StaticRetriever([_candidate("a", 0.5)])
    retriever = RerankingRetriever(
        retriever=inner,
        reranker=PassthroughReranker(),
        rerank_top_k=10,
        fetch_multiplier=4,
    )

    retriever.retrieve(tenant_id=uuid4(), query="q", top_k=10)

    assert inner.last_top_k == 40


def test_reranking_retriever_preserves_hybrid_debug_counters() -> None:
    """answer_service reads these off candidate[0]; reordering must not lose them."""
    items = [
        _candidate(
            "first",
            0.9,
            metadata={
                "hybrid_fts_candidates": 8,
                "hybrid_vector_candidates": 12,
                "hybrid_merged_candidates": 17,
            },
        ),
        _candidate("second", 0.8),
    ]
    retriever = RerankingRetriever(
        retriever=_StaticRetriever(items),
        reranker=_ReversingReranker(),
        rerank_top_k=10,
    )

    result = retriever.retrieve(tenant_id=uuid4(), query="q")

    assert result[0].metadata["hybrid_fts_candidates"] == 8
    assert result[0].metadata["hybrid_vector_candidates"] == 12
    assert result[0].metadata["rerank_input_candidates"] == 2


def test_reranking_retriever_handles_empty_retrieval() -> None:
    retriever = RerankingRetriever(
        retriever=_StaticRetriever([]),
        reranker=_ReversingReranker(),
        rerank_top_k=10,
    )

    assert retriever.retrieve(tenant_id=uuid4(), query="q") == []


def test_passthrough_preserves_order_and_truncates() -> None:
    items = [_candidate(f"c{i}", 1.0 - i / 10) for i in range(5)]

    result = PassthroughReranker().rerank(query="q", candidates=items, top_k=3)

    assert [c.text for c in result] == ["c0", "c1", "c2"]


# --- factory ------------------------------------------------------------


def test_factory_defaults_to_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RERANKER_BACKEND", raising=False)
    assert isinstance(build_reranker(), PassthroughReranker)


@pytest.mark.parametrize("backend", ["none", "off", "passthrough", ""])
def test_factory_disabled_values_give_passthrough(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", backend)
    assert isinstance(build_reranker(), PassthroughReranker)


def test_factory_unknown_backend_degrades_to_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", "not-a-real-backend")
    assert isinstance(build_reranker(), PassthroughReranker)


@pytest.mark.parametrize(
    ("backend", "key"),
    [("cohere", "COHERE_API_KEY"), ("voyage", "VOYAGE_API_KEY")],
)
def test_factory_without_api_key_degrades_to_passthrough(
    monkeypatch: pytest.MonkeyPatch, backend: str, key: str
) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", backend)
    monkeypatch.delenv(key, raising=False)
    assert isinstance(build_reranker(), PassthroughReranker)


def test_factory_builds_cohere_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", "cohere")
    monkeypatch.setenv("COHERE_API_KEY", "stub")
    assert isinstance(build_reranker(), CohereReranker)


def test_factory_builds_voyage_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "stub")
    assert isinstance(build_reranker(), VoyageReranker)


def test_factory_azure_backend_needs_a_chat_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RERANKER_BACKEND", "azure_llm")
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT", raising=False)
    assert isinstance(build_reranker(), PassthroughReranker)


# --- hosted providers ---------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_cohere_reranker_applies_returned_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    payload = {
        "results": [
            {"index": 1, "relevance_score": 0.97},
            {"index": 0, "relevance_score": 0.21},
        ]
    }
    monkeypatch.setattr(
        "packages.reranking.http_rerankers.requests.post",
        lambda *a, **k: _FakeResponse(200, payload),
    )

    result = CohereReranker(api_key="stub").rerank(query="q", candidates=items, top_k=2)

    assert [c.text for c in result] == ["second", "first"]
    assert result[0].metadata["rerank_score"] == 0.97
    assert result[0].metadata["rerank_provider"] == "cohere"
    assert result[0].metadata["pre_rerank_score"] == 0.8


def test_hosted_reranker_passthrough_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    monkeypatch.setattr(
        "packages.reranking.http_rerankers.requests.post",
        lambda *a, **k: _FakeResponse(500, text="boom"),
    )

    result = CohereReranker(api_key="stub").rerank(query="q", candidates=items, top_k=2)

    assert [c.text for c in result] == ["first", "second"]


def test_hosted_reranker_passthrough_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]

    def boom(*args: Any, **kwargs: Any) -> None:
        raise requests.ConnectionError("down")

    monkeypatch.setattr("packages.reranking.http_rerankers.requests.post", boom)

    result = VoyageReranker(api_key="stub").rerank(query="q", candidates=items, top_k=2)

    assert [c.text for c in result] == ["first", "second"]


def test_hosted_reranker_ignores_out_of_range_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_candidate("first", 0.9)]
    payload = {"results": [{"index": 7, "relevance_score": 0.9}]}
    monkeypatch.setattr(
        "packages.reranking.http_rerankers.requests.post",
        lambda *a, **k: _FakeResponse(200, payload),
    )

    # single candidate short-circuits, so use two to reach the parser
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    result = CohereReranker(api_key="stub").rerank(query="q", candidates=items, top_k=2)

    assert [c.text for c in result] == ["first", "second"]


# --- azure llm reranker -------------------------------------------------


class _ScriptedLlm(LlmClient):
    def __init__(self, reply: str | None = None, fail: bool = False) -> None:
        super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")
        self._reply = reply
        self._fail = fail

    def complete(self, system_prompt: str, user_message: str) -> str:
        if self._fail:
            raise LlmError("upstream down")
        return self._reply or ""


def test_azure_reranker_orders_by_model_score() -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    reply = json.dumps([{"index": 1, "score": 2}, {"index": 2, "score": 9}])

    result = AzureLlmReranker(llm=_ScriptedLlm(reply)).rerank(
        query="q", candidates=items, top_k=2
    )

    assert [c.text for c in result] == ["second", "first"]
    assert result[0].metadata["rerank_score"] == 0.9
    assert result[0].metadata["rerank_provider"] == "azure_llm"


def test_azure_reranker_tolerates_fenced_json() -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    reply = '```json\n[{"index": 2, "score": 10}, {"index": 1, "score": 1}]\n```'

    result = AzureLlmReranker(llm=_ScriptedLlm(reply)).rerank(
        query="q", candidates=items, top_k=2
    )

    assert [c.text for c in result] == ["second", "first"]


def test_azure_reranker_keeps_unscored_candidates() -> None:
    """A partial reply must not silently drop evidence."""
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    reply = json.dumps([{"index": 2, "score": 7}])

    result = AzureLlmReranker(llm=_ScriptedLlm(reply)).rerank(
        query="q", candidates=items, top_k=5
    )

    assert len(result) == 2
    assert result[0].text == "second"


def test_azure_reranker_passthrough_on_llm_failure() -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]

    result = AzureLlmReranker(llm=_ScriptedLlm(fail=True)).rerank(
        query="q", candidates=items, top_k=2
    )

    assert [c.text for c in result] == ["first", "second"]


def test_azure_reranker_passthrough_on_unparseable_reply() -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]

    result = AzureLlmReranker(llm=_ScriptedLlm("I cannot do that")).rerank(
        query="q", candidates=items, top_k=2
    )

    assert [c.text for c in result] == ["first", "second"]


def test_azure_reranker_passthrough_when_unconfigured() -> None:
    items = [_candidate("first", 0.9), _candidate("second", 0.8)]
    unconfigured = LlmClient(endpoint="", api_key="", deployment="")

    result = AzureLlmReranker(llm=unconfigured).rerank(
        query="q", candidates=items, top_k=2
    )

    assert [c.text for c in result] == ["first", "second"]
