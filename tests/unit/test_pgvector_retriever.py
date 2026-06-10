from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from packages.retrieval.pgvector_provider import PgVectorRetriever


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, stmt, params):
        self.calls += 1
        return _FakeResult(self.rows)


def test_pgvector_retriever_returns_correct_section_for_deadline_query() -> None:
    policy_id = uuid4()
    policy_version_id = uuid4()
    section_id = uuid4()

    rows = [
        SimpleNamespace(
            policy_id=policy_id,
            policy_name="Appeals Policy",
            policy_version_id=policy_version_id,
            section_id=section_id,
            section_text="Members may file an appeal within 90 days of notice.",
            section_path="Member Appeals",
            section_title="Appeals",
            section_index=1,
            is_current=True,
            effective_date=date(2026, 3, 1),
            authority_level=80,
            department_scope="all",
            policy_type="claims",
            public_url="https://example.org/policies/appeals",
            distance=0.12,
        )
    ]

    session = _FakeSession(rows)
    retriever = PgVectorRetriever(session=session, embedder=lambda texts: [[0.1, 0.2, 0.3]])

    candidates = retriever.retrieve(tenant_id=uuid4(), query="deadline to file an appeal", top_k=5)

    assert session.calls == 1
    assert len(candidates) == 1
    assert "within 90 days" in candidates[0].text
    assert candidates[0].source == "pgvector"
    assert candidates[0].metadata["department_scope"] == "all"
    assert candidates[0].metadata["policy_name"] == "Appeals Policy"
    assert candidates[0].metadata["public_url"] == "https://example.org/policies/appeals"
