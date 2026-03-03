from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankingWeights:
	authority: float = 1.0
	recency: float = 1.0
	department_match: float = 1.0
	role_match: float = 1.0
	base_relevance: float = 1.0
