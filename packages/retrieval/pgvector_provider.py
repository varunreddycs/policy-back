from __future__ import annotations

from typing import List
from uuid import UUID

from packages.core.dtos import EvidenceCandidate
from packages.retrieval.base import IVectorRetriever


class PgVectorRetriever(IVectorRetriever):
	"""pgvector retriever (Phase 2 scaffold)."""

	def retrieve(self, *, tenant_id: UUID, query: str, scope=None, user=None, top_k: int = 10) -> List[EvidenceCandidate]:
		return []


# Back-compat alias (older name)
PgvectorRetriever = PgVectorRetriever
