"""S2: point-in-time "as-of" answers."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from packages.core.dtos import (
    AskRequest,
    EvidenceCandidate,
    PolicyScope,
    UserContext,
)
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever
from packages.retrieval.cosmos_vector_provider import CosmosVectorRetriever
from packages.retrieval.pgsql_fts_provider import PgsqlFtsRetriever

AS_OF = date(2025, 3, 15)


class _RecordingRetriever(IVectorRetriever):
    """Captures the scope the answer service actually hands to retrieval."""

    def __init__(self, items: list[EvidenceCandidate] | None = None) -> None:
        self._items = items or []
        self.seen_scope: PolicyScope | None = None

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        scope: PolicyScope | None = None,
        user: UserContext | None = None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        self.seen_scope = scope
        return self._items


def _candidate(
    effective: str, *, version_label: str | None = None
) -> EvidenceCandidate:
    return EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Submit within 30 days of the event.",
        score=0.9,
        source="hybrid",
        metadata={
            "department_scope": "all",
            "is_current": True,
            "effective_date": effective,
            "version_label": version_label,
            "vector_similarity": 0.8,
        },
    )


def _request(**overrides) -> AskRequest:
    tid = uuid4()
    payload = {
        "tenant_id": tid,
        "question": "What is the deadline?",
        "user": UserContext(tenant_id=tid),
    }
    payload.update(overrides)
    return AskRequest(**payload)


# --- as_of flows to retrieval --------------------------------------------


def test_as_of_is_merged_into_the_retrieval_scope() -> None:
    retriever = _RecordingRetriever()

    AnswerService(retriever=retriever).ask(_request(as_of=AS_OF))

    assert retriever.seen_scope is not None
    assert retriever.seen_scope.as_of == AS_OF


def test_as_of_preserves_an_existing_scope() -> None:
    retriever = _RecordingRetriever()
    scope = PolicyScope(policy_types=["hr"], only_current=False)

    AnswerService(retriever=retriever).ask(_request(as_of=AS_OF, scope=scope))

    assert retriever.seen_scope is not None
    assert retriever.seen_scope.as_of == AS_OF
    assert retriever.seen_scope.policy_types == ["hr"]
    assert retriever.seen_scope.only_current is False


def test_without_as_of_the_scope_is_passed_through_untouched() -> None:
    retriever = _RecordingRetriever()
    scope = PolicyScope(policy_types=["hr"])

    AnswerService(retriever=retriever).ask(_request(scope=scope))

    assert retriever.seen_scope is scope
    assert scope.as_of is None


# --- surfacing ------------------------------------------------------------


def test_decision_and_citations_surface_the_pinned_date() -> None:
    candidate = _candidate("2025-01-01", version_label="v2.1")
    response = AnswerService(retriever=_RecordingRetriever([candidate])).ask(
        _request(as_of=AS_OF)
    )

    assert response.decision is not None
    assert response.decision.as_of == AS_OF
    assert response.citation_items
    assert response.citation_items[0].effective_date == date(2025, 1, 1)
    assert response.citation_items[0].version_label == "v2.1"


def test_decision_as_of_is_none_for_present_day_questions() -> None:
    response = AnswerService(
        retriever=_RecordingRetriever([_candidate("2025-01-01")])
    ).ask(_request())

    assert response.decision is not None
    assert response.decision.as_of is None


# --- postgres predicate ----------------------------------------------------


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, stmt, params=None):
        self.statements.append(
            str(stmt.compile(compile_kwargs={"literal_binds": False}))
        )

        class _Empty:
            def all(self) -> list:
                return []

        return _Empty()


def test_fts_as_of_replaces_the_is_current_filter() -> None:
    session = _CapturingSession()
    retriever = PgsqlFtsRetriever(session=session)  # type: ignore[arg-type]

    retriever.retrieve(
        tenant_id=uuid4(),
        query="deadline",
        scope=PolicyScope(as_of=AS_OF),
    )

    sql = session.statements[0]
    assert "NOT (EXISTS" in sql, "supersession must be excluded via NOT EXISTS"
    assert "effective_date" in sql
    assert "version_number" in sql, "same-day ties break on version_number"
    assert "is_current = true" not in sql.lower(), "as_of replaces is_current"


def test_fts_without_as_of_keeps_the_is_current_filter() -> None:
    session = _CapturingSession()
    retriever = PgsqlFtsRetriever(session=session)  # type: ignore[arg-type]

    retriever.retrieve(tenant_id=uuid4(), query="deadline", scope=PolicyScope())

    sql = session.statements[0]
    assert "is_current IS true" in sql or "is_current = true" in sql.lower()
    assert "NOT (EXISTS" not in sql


# --- cosmos best-effort ----------------------------------------------------


class _FakeContainer:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def query_items(self, **kwargs) -> list[dict]:
        return self._rows


def _cosmos_row(policy_id: str, version_id: str, effective: str | None) -> dict:
    return {
        "policy_id": policy_id,
        "policy_version_id": version_id,
        "policy_section_id": str(uuid4()),
        "text": "Submit within 30 days.",
        "similarity_score": 0.8,
        "is_current": False,
        "effective_date": effective,
        "department_scope": "all",
        "authority_level": 50,
    }


def _cosmos_retriever(rows: list[dict]) -> CosmosVectorRetriever:
    return CosmosVectorRetriever(
        embeddings_container=_FakeContainer(rows),
        embed_fn=lambda _q: [0.0] * 8,
    )


def test_cosmos_as_of_keeps_the_version_authoritative_on_the_date() -> None:
    pid = str(uuid4())
    v_old, v_new, v_future = str(uuid4()), str(uuid4()), str(uuid4())
    rows = [
        _cosmos_row(pid, v_old, "2024-06-01"),
        _cosmos_row(pid, v_new, "2025-02-01"),  # authoritative on AS_OF
        _cosmos_row(pid, v_future, "2025-09-01"),  # not yet effective
    ]

    results = _cosmos_retriever(rows).retrieve(
        tenant_id=uuid4(), query="deadline", scope=PolicyScope(as_of=AS_OF)
    )

    versions = {str(c.policy_version_id) for c in results}
    assert versions == {v_new}
    assert results[0].metadata["is_current"] is True
    assert results[0].metadata["as_of"] == AS_OF.isoformat()


def test_cosmos_as_of_is_scoped_per_policy() -> None:
    p1, p2 = str(uuid4()), str(uuid4())
    v1, v2 = str(uuid4()), str(uuid4())
    rows = [
        _cosmos_row(p1, v1, "2024-06-01"),
        _cosmos_row(p2, v2, "2025-01-01"),
    ]

    results = _cosmos_retriever(rows).retrieve(
        tenant_id=uuid4(), query="deadline", scope=PolicyScope(as_of=AS_OF)
    )

    assert {str(c.policy_version_id) for c in results} == {v1, v2}


def test_cosmos_without_as_of_is_untouched() -> None:
    pid = str(uuid4())
    rows = [
        _cosmos_row(pid, str(uuid4()), "2024-06-01"),
        _cosmos_row(pid, str(uuid4()), "2025-09-01"),
    ]

    results = _cosmos_retriever(rows).retrieve(
        tenant_id=uuid4(), query="deadline", scope=PolicyScope()
    )

    assert len(results) == 2
