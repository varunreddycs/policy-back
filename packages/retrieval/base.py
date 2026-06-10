from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List
from uuid import UUID

from packages.core.dtos import EvidenceCandidate

try:  # avoid import cycles in type-check-only contexts
	from packages.core.dtos import PolicyScope, UserContext
except Exception:  # pragma: no cover
	PolicyScope = object  # type: ignore
	UserContext = object  # type: ignore


class IVectorRetriever(ABC):
	"""Interface for retrieval backends (Azure Search, pgvector, etc)."""

	@abstractmethod
	def retrieve(
		self,
		*,
		tenant_id: UUID,
		query: str,
		scope: "PolicyScope | None" = None,
		user: "UserContext | None" = None,
		top_k: int = 10,
	) -> List[EvidenceCandidate]:
		raise NotImplementedError
