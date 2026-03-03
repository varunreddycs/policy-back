from __future__ import annotations

from typing import List

from packages.core.dtos import EvidenceCandidate
from packages.ranking.weights import RankingWeights


class PolicyRanker:
	"""Business ranking for evidence candidates (Phase 2 scaffold)."""

	def __init__(self, weights: RankingWeights | None = None) -> None:
		self._weights = weights or RankingWeights()

	def rank(self, candidates: List[EvidenceCandidate]) -> List[EvidenceCandidate]:
		# TODO: implement authority/department/role scoring.
		return sorted(candidates, key=lambda c: c.score, reverse=True)
