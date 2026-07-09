"""Phase 3.1 — resolve ExtractedReferences to concrete IDs.

Resolution is best-effort and tenant-scoped. Unresolved internal/cross-policy
refs are still returned as `PolicyReference` rows with
`resolution_status='unresolved'` so we don't lose signal — they can be
re-resolved later when the target version is ingested.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models.policy_models import (
	Policy,
	PolicyReference,
	PolicySection,
	PolicyVersion,
)
from packages.db.repositories.repo_dtos import PolicySectionDTO
from packages.extraction.reference_extractor import EXTRACTOR_VERSION, ExtractedReference


# Section rows for path matching: (section_id, section_path, section_index).
_SectionRow = Tuple[uuid.UUID, Optional[str], Optional[int]]


def _match_section_path(
	rows: Sequence[_SectionRow],
	parsed_section_path: str,
) -> Optional[uuid.UUID]:
	"""Pure section-path matcher shared by the ORM and DTO resolution paths.

	Strategy: (1) exact section_path, (2) token-bounded contains, (3) integer
	fallback against section_index.
	"""
	if not parsed_section_path:
		return None

	exact: Optional[uuid.UUID] = None
	contains: Optional[uuid.UUID] = None
	for sid, path, _idx in rows:
		if path == parsed_section_path:
			exact = sid
			break
		# token-bounded contains: avoid "3.2" matching "13.21"
		if re.search(rf"(?:^|\s|-){re.escape(parsed_section_path)}(?:\s|$|[^\d.])", path or ""):
			if contains is None:
				contains = sid
	if exact:
		return exact
	if contains:
		return contains

	if parsed_section_path.isdigit():
		idx = int(parsed_section_path)
		for sid, _path, sec_idx in rows:
			if sec_idx == idx:
				return sid

	return None


# ---------------------------------------------------------------------------
# Internal section resolution
# ---------------------------------------------------------------------------


def _resolve_internal_section(
	session: Session,
	*,
	tenant_id: uuid.UUID,
	source_policy_version_id: uuid.UUID,
	parsed_section_path: str,
) -> Optional[uuid.UUID]:
	"""Find a section in the same policy_version whose section_path matches.

	The worker writes `section_path` from the extractor's `section_key`, which
	may not be a clean dotted number. We try three strategies in order:

	1. Exact match on section_path.
	2. section_path that contains the parsed path as a token (e.g.
	   "3.2 Eligibility" matches "3.2").
	3. section_index match — useful when paths are like "section-3" and the
	   parsed value is the integer "3".
	"""
	if not parsed_section_path:
		return None

	stmt = (
		select(PolicySection.id, PolicySection.section_path, PolicySection.section_index)
		.where(
			PolicySection.tenant_id == tenant_id,
			PolicySection.policy_version_id == source_policy_version_id,
			PolicySection.section_path.isnot(None),
		)
	)
	rows = [(sid, path, idx) for sid, path, idx in session.execute(stmt).all()]
	return _match_section_path(rows, parsed_section_path)


# ---------------------------------------------------------------------------
# Cross-policy resolution (token-overlap fuzzy match)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_STOP_TOKENS = {"the", "a", "an", "of", "and", "policy", "sop", "procedure", "guideline", "standard"}


def _tokenize(name: str) -> set[str]:
	return {t.lower() for t in _TOKEN_RE.findall(name) if t.lower() not in _STOP_TOKENS}


def _name_score(query: str, candidate: str) -> float:
	q = _tokenize(query)
	c = _tokenize(candidate)
	if not q or not c:
		return 0.0
	overlap = q & c
	return len(overlap) / max(len(q), len(c))


@dataclass(frozen=True)
class _PolicyCandidate:
	id: uuid.UUID
	name: str


def _load_tenant_policies(session: Session, tenant_id: uuid.UUID) -> List[_PolicyCandidate]:
	stmt = select(Policy.id, Policy.name).where(Policy.tenant_id == tenant_id)
	return [_PolicyCandidate(id=row[0], name=row[1]) for row in session.execute(stmt).all()]


def _resolve_cross_policy(
	candidates: Sequence[_PolicyCandidate],
	matched_text: str,
	*,
	threshold: float = 0.6,
) -> Optional[uuid.UUID]:
	best: Optional[uuid.UUID] = None
	best_score = 0.0
	for cand in candidates:
		score = _name_score(matched_text, cand.name)
		if score > best_score:
			best_score = score
			best = cand.id
	if best_score >= threshold:
		return best
	return None


# ---------------------------------------------------------------------------
# Top-level resolver
# ---------------------------------------------------------------------------


def resolve_references(
	session: Session,
	*,
	source_section: PolicySection,
	source_policy_id: uuid.UUID,
	extracted: Iterable[ExtractedReference],
) -> List[PolicyReference]:
	"""Convert ExtractedReferences into unsaved PolicyReference rows.

	The caller is responsible for adding/committing the returned rows. This
	function only reads from the DB (to look up resolution targets).
	"""
	extracted_list = list(extracted)
	if not extracted_list:
		return []

	# Lazy-load tenant policies only if we actually have a cross-policy ref.
	tenant_policies: Optional[List[_PolicyCandidate]] = None

	# Skip self-references when resolving internal refs (would be noise).
	source_section_id = source_section.id
	tenant_id = source_section.tenant_id
	source_policy_version_id = source_section.policy_version_id

	out: List[PolicyReference] = []
	for ref in extracted_list:
		row = PolicyReference(
			tenant_id=tenant_id,
			source_section_id=source_section_id,
			source_policy_version_id=source_policy_version_id,
			reference_type=ref.reference_type,
			resolution_status="unresolved",
			matched_text=ref.matched_text,
			match_offset=ref.match_offset,
			extractor_version=ref.extractor_version or EXTRACTOR_VERSION,
			confidence=float(ref.confidence),
		)

		if ref.reference_type == "internal_section":
			target_section_id = _resolve_internal_section(
				session,
				tenant_id=tenant_id,
				source_policy_version_id=source_policy_version_id,
				parsed_section_path=ref.parsed_section_path or "",
			)
			# Don't store self-references — they're noise from a section
			# pointing at its own number in body text.
			if target_section_id == source_section_id:
				continue
			if target_section_id is not None:
				row.target_section_id = target_section_id
				row.target_policy_id = source_policy_id
				row.resolution_status = "resolved"

		elif ref.reference_type == "cross_policy":
			if tenant_policies is None:
				tenant_policies = _load_tenant_policies(session, tenant_id)
			target_policy_id = _resolve_cross_policy(tenant_policies, ref.matched_text)
			# Don't store self-references at the policy level either.
			if target_policy_id == source_policy_id:
				continue
			if target_policy_id is not None:
				row.target_policy_id = target_policy_id
				row.resolution_status = "resolved"

		elif ref.reference_type == "external_authority":
			row.resolution_status = "external"
			row.target_external_uri = ref.external_uri
			row.target_external_label = ref.external_label or ref.matched_text

		else:
			# Unknown type — skip rather than insert garbage.
			continue

		out.append(row)

	return out


def extract_and_resolve_for_version(
	session: Session,
	*,
	policy_version: PolicyVersion,
) -> List[PolicyReference]:
	"""Run extraction + resolution for every section in a policy version.

	Returns the list of unsaved PolicyReference rows. The caller is
	responsible for the persistence strategy (delete-then-insert vs upsert)
	and for committing.
	"""
	from packages.extraction.reference_extractor import extract_references

	policy_id = policy_version.policy_id
	all_rows: List[PolicyReference] = []
	for section in policy_version.sections:
		extracted = extract_references(section.text or "")
		if not extracted:
			continue
		rows = resolve_references(
			session,
			source_section=section,
			source_policy_id=policy_id,
			extracted=extracted,
		)
		all_rows.extend(rows)
	return all_rows


# ---------------------------------------------------------------------------
# Backend-agnostic resolution (DTO + repository driven)
# ---------------------------------------------------------------------------
#
# These mirror resolve_references / extract_and_resolve_for_version but operate
# on portable DTOs and return plain dicts ready for IReferenceRepository.
# bulk_insert — so the same logic works against PostgreSQL or Cosmos DB.


def resolve_references_from_dtos(
	*,
	source_section: PolicySectionDTO,
	source_policy_id: uuid.UUID,
	sibling_rows: Sequence[_SectionRow],
	tenant_policies: Sequence["_PolicyCandidate"],
	extracted: Iterable[ExtractedReference],
) -> List[Dict[str, Any]]:
	"""DTO-based variant of :func:`resolve_references`.

	Returns dicts whose keys match the ``PolicyReference`` columns, suitable for
	``IReferenceRepository.bulk_insert`` on any backend.
	"""
	extracted_list = list(extracted)
	if not extracted_list:
		return []

	source_section_id = source_section.id
	tenant_id = source_section.tenant_id
	source_policy_version_id = source_section.policy_version_id

	out: List[Dict[str, Any]] = []
	for ref in extracted_list:
		row: Dict[str, Any] = {
			"tenant_id": tenant_id,
			"source_section_id": source_section_id,
			"source_policy_version_id": source_policy_version_id,
			"reference_type": ref.reference_type,
			"resolution_status": "unresolved",
			"matched_text": ref.matched_text,
			"match_offset": ref.match_offset,
			"extractor_version": ref.extractor_version or EXTRACTOR_VERSION,
			"confidence": float(ref.confidence),
			"target_section_id": None,
			"target_policy_id": None,
			"target_external_uri": None,
			"target_external_label": None,
		}

		if ref.reference_type == "internal_section":
			target_section_id = _match_section_path(sibling_rows, ref.parsed_section_path or "")
			if target_section_id == source_section_id:
				continue
			if target_section_id is not None:
				row["target_section_id"] = target_section_id
				row["target_policy_id"] = source_policy_id
				row["resolution_status"] = "resolved"

		elif ref.reference_type == "cross_policy":
			target_policy_id = _resolve_cross_policy(tenant_policies, ref.matched_text)
			if target_policy_id == source_policy_id:
				continue
			if target_policy_id is not None:
				row["target_policy_id"] = target_policy_id
				row["resolution_status"] = "resolved"

		elif ref.reference_type == "external_authority":
			row["resolution_status"] = "external"
			row["target_external_uri"] = ref.external_uri
			row["target_external_label"] = ref.external_label or ref.matched_text

		else:
			continue

		out.append(row)

	return out


def extract_and_resolve_for_sections(
	*,
	sections: Sequence[PolicySectionDTO],
	source_policy_id: uuid.UUID,
	tenant_policies: Sequence[Tuple[uuid.UUID, str]],
) -> List[Dict[str, Any]]:
	"""Backend-agnostic variant of :func:`extract_and_resolve_for_version`.

	``sections`` must be every section of the source policy version (used both
	as work items and as internal-resolution targets). ``tenant_policies`` is
	the ``(policy_id, name)`` set for cross-policy fuzzy resolution.
	"""
	from packages.extraction.reference_extractor import extract_references

	sibling_rows: List[_SectionRow] = [
		(s.id, s.section_path, s.section_index) for s in sections
	]
	candidates = [_PolicyCandidate(id=pid, name=name) for pid, name in tenant_policies]

	out: List[Dict[str, Any]] = []
	for section in sections:
		extracted = extract_references(section.text or "")
		if not extracted:
			continue
		out.extend(
			resolve_references_from_dtos(
				source_section=section,
				source_policy_id=source_policy_id,
				sibling_rows=sibling_rows,
				tenant_policies=candidates,
				extracted=extracted,
			)
		)
	return out
