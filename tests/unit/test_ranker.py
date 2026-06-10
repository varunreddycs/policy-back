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
	dept_v = uuid4()
	org_v = uuid4()

	dept = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=dept_v,
		section_id=None,
		text="Department SOP says submission deadline is 90 days",
		score=0.2,
		source="test",
		metadata={
			"department_scope": "operations",
			"authority_level": 10,
			"effective_date": "2026-02-01",
			"is_current": True,
		},
	)

	organization = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=org_v,
		section_id=None,
		text="Organization guidance says submission deadline is 60 days",
		score=0.9,
		source="test",
		metadata={
			"department_scope": "all",
			"authority_level": 90,
			"effective_date": "2026-03-01",
			"is_current": True,
		},
	)

	# operations: department bucket A exists, so it must win even if organization scores higher.
	operations = [
		dept.model_copy(update={"metadata": {**dept.metadata, "user_department": "operations"}}),
		organization.model_copy(update={"metadata": {**organization.metadata, "user_department": "operations"}}),
	]
	ranked_operations = ranker.rank(operations)
	assert "90 days" in ranked_operations[0].text

	# compliance: no matching dept-scoped evidence, so fall back to 'all'.
	compliance = [
		dept.model_copy(update={"metadata": {**dept.metadata, "user_department": "compliance"}}),
		organization.model_copy(update={"metadata": {**organization.metadata, "user_department": "compliance"}}),
	]
	ranked_compliance = ranker.rank(compliance)
	assert "60 days" in ranked_compliance[0].text


def test_policy_ranker_sorts_by_final_score_within_bucket() -> None:
	ranker = PolicyRanker()

	policy_id = uuid4()
	version_id = uuid4()

	low = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=version_id,
		section_id=None,
		text="lower score",
		score=0.20,
		source="hybrid",
		metadata={"department_scope": "operations", "user_department": "operations", "authority_level": 50, "is_current": True},
	)
	high = EvidenceCandidate(
		policy_id=policy_id,
		policy_version_id=version_id,
		section_id=None,
		text="higher score",
		score=0.95,
		source="hybrid",
		metadata={"department_scope": "operations", "user_department": "operations", "authority_level": 10, "is_current": False},
	)

	ranked = ranker.rank([low, high])
	assert ranked[0].text == "higher score"
