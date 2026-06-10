from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from packages.extraction.reference_extractor import ExtractedReference
from packages.extraction.reference_resolver import (
	_name_score,
	_resolve_cross_policy,
	_PolicyCandidate,
	resolve_references,
)


# ---------------------------------------------------------------------------
# Cross-policy fuzzy matcher (pure)
# ---------------------------------------------------------------------------


def test_name_score_token_overlap() -> None:
	assert _name_score("Enterprise Appeals Policy", "Enterprise Appeals Policy") == 1.0
	# 'Policy' is a stop token; "Appeals" / "Enterprise" are the meaningful tokens.
	assert _name_score("Enterprise Appeals Policy", "Enterprise Grievance Policy") == 0.5
	assert _name_score("Foo Bar", "Completely Unrelated") == 0.0


def test_resolve_cross_policy_picks_best_above_threshold() -> None:
	a, b = uuid4(), uuid4()
	candidates = [
		_PolicyCandidate(id=a, name="Enterprise Appeals Policy"),
		_PolicyCandidate(id=b, name="Member Privacy Policy"),
	]
	picked = _resolve_cross_policy(candidates, "Enterprise Appeals Policy")
	assert picked == a


def test_resolve_cross_policy_returns_none_below_threshold() -> None:
	candidates = [
		_PolicyCandidate(id=uuid4(), name="Member Privacy Policy"),
	]
	assert _resolve_cross_policy(candidates, "Enterprise Appeals Policy") is None


# ---------------------------------------------------------------------------
# Top-level resolver — uses a fake session that returns canned rows
# ---------------------------------------------------------------------------


class _FakeResult:
	def __init__(self, rows):
		self._rows = rows

	def all(self):
		return self._rows

	def first(self):
		return self._rows[0] if self._rows else None

	def scalar_one_or_none(self):
		return self._rows[0] if self._rows else None


class _FakeSession:
	"""Tiny stub that returns the next queued result on each .execute() call."""

	def __init__(self, queued_results):
		self._queue = list(queued_results)

	def execute(self, _stmt):
		if not self._queue:
			return _FakeResult([])
		return self._queue.pop(0)


def _make_section(*, section_id, tenant_id, policy_version_id):
	return SimpleNamespace(
		id=section_id,
		tenant_id=tenant_id,
		policy_version_id=policy_version_id,
	)


def test_external_authority_marks_resolution_external() -> None:
	tenant = uuid4()
	policy = uuid4()
	version = uuid4()
	section_id = uuid4()
	section = _make_section(section_id=section_id, tenant_id=tenant, policy_version_id=version)

	extracted = [
		ExtractedReference(
			reference_type="external_authority",
			matched_text="HIPAA",
			match_offset=10,
			external_label="HIPAA",
		)
	]

	# External refs do not query the DB.
	rows = resolve_references(
		_FakeSession([]),
		source_section=section,
		source_policy_id=policy,
		extracted=extracted,
	)

	assert len(rows) == 1
	r = rows[0]
	assert r.resolution_status == "external"
	assert r.target_external_label == "HIPAA"
	assert r.target_section_id is None
	assert r.target_policy_id is None


def test_internal_section_resolved_via_section_path_exact_match() -> None:
	tenant = uuid4()
	policy = uuid4()
	version = uuid4()
	source_id = uuid4()
	target_id = uuid4()

	section = _make_section(section_id=source_id, tenant_id=tenant, policy_version_id=version)

	# First .execute() inside _resolve_internal_section returns the candidate sections.
	rows_for_lookup = [
		(source_id, "1.0", 0),
		(target_id, "3.2", 5),
	]
	fake = _FakeSession([_FakeResult(rows_for_lookup)])

	extracted = [
		ExtractedReference(
			reference_type="internal_section",
			matched_text="§3.2",
			match_offset=12,
			parsed_section_path="3.2",
		)
	]

	rows = resolve_references(
		fake,
		source_section=section,
		source_policy_id=policy,
		extracted=extracted,
	)

	assert len(rows) == 1
	r = rows[0]
	assert r.resolution_status == "resolved"
	assert r.target_section_id == target_id
	assert r.target_policy_id == policy


def test_internal_section_unresolved_when_no_match() -> None:
	tenant = uuid4()
	policy = uuid4()
	version = uuid4()
	source_id = uuid4()

	section = _make_section(section_id=source_id, tenant_id=tenant, policy_version_id=version)
	fake = _FakeSession([_FakeResult([(source_id, "1.0", 0)])])

	extracted = [
		ExtractedReference(
			reference_type="internal_section",
			matched_text="§9.9",
			match_offset=0,
			parsed_section_path="9.9",
		)
	]

	rows = resolve_references(
		fake,
		source_section=section,
		source_policy_id=policy,
		extracted=extracted,
	)

	assert len(rows) == 1
	assert rows[0].resolution_status == "unresolved"
	assert rows[0].target_section_id is None


def test_internal_self_reference_is_dropped() -> None:
	tenant = uuid4()
	policy = uuid4()
	version = uuid4()
	source_id = uuid4()

	section = _make_section(section_id=source_id, tenant_id=tenant, policy_version_id=version)
	# Lookup returns the source section itself as the only candidate.
	fake = _FakeSession([_FakeResult([(source_id, "3.2", 0)])])

	extracted = [
		ExtractedReference(
			reference_type="internal_section",
			matched_text="§3.2",
			match_offset=0,
			parsed_section_path="3.2",
		)
	]

	rows = resolve_references(
		fake,
		source_section=section,
		source_policy_id=policy,
		extracted=extracted,
	)
	assert rows == []


def test_cross_policy_resolved_to_target_policy_id() -> None:
	tenant = uuid4()
	source_policy = uuid4()
	target_policy = uuid4()
	version = uuid4()
	source_id = uuid4()

	section = _make_section(section_id=source_id, tenant_id=tenant, policy_version_id=version)

	# resolver lazy-loads tenant policies via one .execute()
	policies_rows = [
		(target_policy, "Enterprise Appeals Policy"),
		(uuid4(), "Member Privacy Policy"),
	]
	fake = _FakeSession([_FakeResult(policies_rows)])

	extracted = [
		ExtractedReference(
			reference_type="cross_policy",
			matched_text="Enterprise Appeals Policy",
			match_offset=20,
		)
	]

	rows = resolve_references(
		fake,
		source_section=section,
		source_policy_id=source_policy,
		extracted=extracted,
	)

	assert len(rows) == 1
	r = rows[0]
	assert r.resolution_status == "resolved"
	assert r.target_policy_id == target_policy
	assert r.target_section_id is None


def test_cross_policy_self_reference_is_dropped() -> None:
	tenant = uuid4()
	source_policy = uuid4()
	version = uuid4()
	source_id = uuid4()
	section = _make_section(section_id=source_id, tenant_id=tenant, policy_version_id=version)

	policies_rows = [(source_policy, "Enterprise Appeals Policy")]
	fake = _FakeSession([_FakeResult(policies_rows)])

	extracted = [
		ExtractedReference(
			reference_type="cross_policy",
			matched_text="Enterprise Appeals Policy",
			match_offset=0,
		)
	]
	rows = resolve_references(
		fake,
		source_section=section,
		source_policy_id=source_policy,
		extracted=extracted,
	)
	assert rows == []
