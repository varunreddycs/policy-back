from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List
from uuid import UUID

from packages.core.dtos import EvidenceCandidate
from packages.ranking.weights import RankingWeights


class PolicyRanker:
	"""Business ranking for evidence candidates (Phase 2 scaffold)."""

	def __init__(self, weights: RankingWeights | None = None) -> None:
		self._weights = weights or RankingWeights()

	def rank(self, candidates: List[EvidenceCandidate]) -> List[EvidenceCandidate]:
		if not candidates:
			return []

		def _norm_dept(value: object | None) -> str:
			if value is None:
				return "all"
			text = str(value).strip().lower()
			return text or "all"

		def _get_user_department() -> str | None:
			for c in candidates:
				dept = (c.metadata or {}).get("user_department")
				dept_norm = str(dept).strip().lower() if dept is not None else ""
				if dept_norm:
					return dept_norm
			return None

		user_department = _get_user_department()

		# Rule B: bucket selection happens BEFORE scoring.
		bucket_a: list[EvidenceCandidate] = []
		bucket_b: list[EvidenceCandidate] = []
		for c in candidates:
			policy_dept = _norm_dept((c.metadata or {}).get("department_scope"))
			if user_department and policy_dept == user_department:
				bucket_a.append(c)
			elif policy_dept == "all":
				bucket_b.append(c)

		selected = bucket_a if bucket_a else bucket_b
		if not selected:
			return []

		def _parse_effective_date(metadata: dict) -> datetime | None:
			raw = metadata.get("effective_date")
			if not raw:
				return None
			try:
				# We store as ISO string like "YYYY-MM-DD".
				return datetime.fromisoformat(str(raw)).replace(tzinfo=timezone.utc)
			except Exception:
				try:
					return datetime.combine(date.fromisoformat(str(raw)), datetime.min.time(), tzinfo=timezone.utc)
				except Exception:
					return None

		def _ts(dt: datetime | None) -> float:
			return dt.timestamp() if dt is not None else 0.0

		def _id_text(value: UUID | None) -> str:
			return str(value) if value is not None else ""

		def final_key(c: EvidenceCandidate) -> tuple:
			md = c.metadata or {}
			base = float(c.score or 0.0) * float(self._weights.base_relevance)
			authority_level = float(md.get("authority_level") or 0.0)
			# Keep authority influence bounded.
			authority = (authority_level / 100.0) * float(self._weights.authority)
			is_current = 1.0 if bool(md.get("is_current")) else 0.0
			current_boost = 0.5 * is_current

			eff_dt = _parse_effective_date(md)
			recency_score = 0.0
			if eff_dt is not None:
				days_ago = max(0.0, (datetime.now(timezone.utc) - eff_dt).total_seconds() / 86400.0)
				recency_score = 1.0 / (1.0 + (days_ago / 30.0))
			recency = recency_score * float(self._weights.recency)

			total = base + authority + current_boost + recency
			# Deterministic tie-breakers.
			return (
				total,
				float(c.score or 0.0),
				is_current,
				authority_level,
				_ts(eff_dt),
				_id_text(c.policy_version_id),
				_id_text(c.section_id),
			)

		return sorted(selected, key=final_key, reverse=True)

