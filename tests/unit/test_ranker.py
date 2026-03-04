"""Unit tests for Phase 2 ranker."""
from __future__ import annotations

from uuid import uuid4

from packages.core.dtos import EvidenceCandidate
from packages.ranking.ranker import PolicyRanker


def test_policy_ranker_prefers_higher_score_and_current() -> None:
	ranker = PolicyRanker()

	policy_id = uuid4()
	policy_version_id = uuid4()

	c1 = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=policy_version_id,
		section_id=None,
		text="a",
		score=0.4,
		source="test",
		metadata={"is_current": False, "authority_level": 0, "department_scope": "all"},
	)
	c2 = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=policy_version_id,
		section_id=None,
		text="b",
		score=0.3,
		source="test",
		metadata={"is_current": True, "authority_level": 0, "department_scope": "all"},
	)

	ranked = ranker.rank([c1, c2])
	assert ranked[0].text == "b"


def test_policy_ranker_bucket_first_department_override() -> None:
	ranker = PolicyRanker()

	policy_id = uuid4()
	claims_v = uuid4()
	enterprise_v = uuid4()

	claims = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=claims_v,
		section_id=None,
		text="Claims SOP says appeal deadline is 90 days",
		score=0.2,
		source="test",
		metadata={
			"department_scope": "claims_ops",
			"authority_level": 10,
			"effective_date": "2026-02-01",
			"is_current": True,
		},
	)

	enterprise = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=enterprise_v,
		section_id=None,
		text="Enterprise policy says appeal deadline is 60 days",
		score=0.9,
		source="test",
		metadata={
			"department_scope": "all",
			"authority_level": 90,
			"effective_date": "2026-03-01",
			"is_current": True,
		},
	)

	# claims_ops: department bucket A exists, so it must win even if enterprise scores higher.
	claims_ops = [
		claims.model_copy(update={"metadata": {**claims.metadata, "user_department": "claims_ops"}}),
		enterprise.model_copy(update={"metadata": {**enterprise.metadata, "user_department": "claims_ops"}}),
	]
	ranked_claims = ranker.rank(claims_ops)
	assert "90 days" in ranked_claims[0].text

	# privacy_office: no matching dept-scoped evidence, so fall back to 'all'.
	privacy = [
		claims.model_copy(update={"metadata": {**claims.metadata, "user_department": "privacy_office"}}),
		enterprise.model_copy(update={"metadata": {**enterprise.metadata, "user_department": "privacy_office"}}),
	]
	ranked_privacy = ranker.rank(privacy)
	assert "60 days" in ranked_privacy[0].text
