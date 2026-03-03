from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List
from uuid import UUID

from packages.core.dtos import EvidenceCandidate


class IVectorRetriever(ABC):
	"""Interface for retrieval backends (Azure Search, pgvector, etc)."""

	@abstractmethod
	def retrieve(self, *, tenant_id: UUID, query: str, limit: int = 10) -> List[EvidenceCandidate]:
		raise NotImplementedError
