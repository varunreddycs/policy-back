from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from packages.retrieval.pgsql_fts_provider import PgsqlFtsRetriever


class _FakeResult:
	def all(self):
		return []


class _FakeSession:
	def __init__(self) -> None:
		self.executed = 0

	def execute(self, stmt):
		self.executed += 1
		return _FakeResult()


@dataclass
class _Scope:
	only_current: bool = True
	policy_ids: list | None = None
	policy_types: list | None = None


def test_pgsql_fts_retriever_empty_query_returns_empty_and_does_not_execute() -> None:
	session = _FakeSession()
	retriever = PgsqlFtsRetriever(session=session)

	results = retriever.retrieve(tenant_id=uuid4(), query="   ")
	assert results == []
	assert session.executed == 0


def test_pgsql_fts_retriever_non_empty_query_executes_and_returns_empty_when_no_rows() -> None:
	session = _FakeSession()
	retriever = PgsqlFtsRetriever(session=session)

	results = retriever.retrieve(tenant_id=uuid4(), query="test", scope=_Scope())
	assert results == []
	assert session.executed == 1


def test_pgsql_fts_retriever_multi_term_query_falls_back_to_or_when_and_is_empty() -> None:
	session = _FakeSession()
	retriever = PgsqlFtsRetriever(session=session)

	results = retriever.retrieve(tenant_id=uuid4(), query="deadline appeal", scope=_Scope())
	assert results == []
	assert session.executed == 2
