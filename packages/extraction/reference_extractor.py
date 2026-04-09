"""Phase 3.1 — regex-based reference extraction.

Pure module: no I/O, no DB. Given a section's text, returns a list of
ExtractedReference dataclasses representing references to other sections,
other policies, or external authorities (statutes, URLs).

Resolution to concrete IDs is handled separately by `reference_resolver`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Tuple


EXTRACTOR_VERSION = "regex-v1"


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------
#
# Internal section refs — same-policy pointers like "§3.2", "Section 4.1.2",
# "Subsection 5". The captured group must be the dotted numeric path so the
# resolver can match it against `policy_sections.section_path`.
_INTERNAL_SECTION_PATTERNS: Tuple[Pattern[str], ...] = (
	re.compile(r"§\s*(\d+(?:\.\d+)*)"),
	re.compile(r"\b[Ss]ections?\s+(\d+(?:\.\d+)*)"),
	re.compile(r"\b[Ss]ub[-\s]?sections?\s+(\d+(?:\.\d+)*)"),
)

# Cross-policy refs — phrases that introduce another named policy/SOP/etc.
# Trigger words are case-insensitive (inline (?i:...) flag); the captured policy
# name remains case-sensitive so we only catch properly capitalized titles.
_CROSS_POLICY_PATTERN: Pattern[str] = re.compile(
	r"\b(?i:per|pursuant to|under|in accordance with|see|refer to)\s+"
	r"(?i:the\s+)?"
	r"([A-Z][A-Za-z0-9&\-]*(?:\s+[A-Z][A-Za-z0-9&\-]*)*\s+(?:Policy|SOP|Procedure|Guideline|Standard))"
)

# External authority refs — statutes, regs, URLs, well-known frameworks.
_URL_PATTERN: Pattern[str] = re.compile(r"https?://[^\s)\]\>]+")
_STATUTE_PATTERNS: Tuple[Pattern[str], ...] = (
	re.compile(r"\b\d+\s+CFR\s+§?\s*\d+(?:\.\d+)*\b"),
	re.compile(r"\b\d+\s+U\.?S\.?C\.?\s+§?\s*\d+(?:\.\d+)*\b"),
)
# Bare framework names. Match as standalone tokens to avoid false positives in
# words like "PCIDSS" appearing inside identifiers.
_FRAMEWORK_PATTERN: Pattern[str] = re.compile(
	r"\b(HIPAA|GDPR|SOX|PCI[-\s]?DSS|HITECH|CCPA)\b"
)


@dataclass(frozen=True)
class ExtractedReference:
	reference_type: str  # one of ReferenceType values
	matched_text: str
	match_offset: int
	# For internal refs, the parsed dotted path (e.g. "3.2"). Resolver uses this
	# to look up the target section_path. None for non-internal types.
	parsed_section_path: Optional[str] = None
	# For external authorities: the URL (if any) and a human-readable label.
	external_uri: Optional[str] = None
	external_label: Optional[str] = None
	confidence: float = 1.0
	extractor_version: str = EXTRACTOR_VERSION


def _extract_internal_section_refs(text: str) -> List[ExtractedReference]:
	out: List[ExtractedReference] = []
	for pattern in _INTERNAL_SECTION_PATTERNS:
		for m in pattern.finditer(text):
			path = m.group(1)
			out.append(
				ExtractedReference(
					reference_type="internal_section",
					matched_text=m.group(0),
					match_offset=m.start(),
					parsed_section_path=path,
				)
			)
	return out


def _extract_cross_policy_refs(text: str) -> List[ExtractedReference]:
	out: List[ExtractedReference] = []
	for m in _CROSS_POLICY_PATTERN.finditer(text):
		name = m.group(1).strip()
		out.append(
			ExtractedReference(
				reference_type="cross_policy",
				matched_text=name,
				match_offset=m.start(1),
				external_label=None,
			)
		)
	return out


def _extract_external_authority_refs(text: str) -> List[ExtractedReference]:
	out: List[ExtractedReference] = []

	for m in _URL_PATTERN.finditer(text):
		uri = m.group(0).rstrip(".,;")
		out.append(
			ExtractedReference(
				reference_type="external_authority",
				matched_text=uri,
				match_offset=m.start(),
				external_uri=uri,
				external_label=uri,
			)
		)

	for pattern in _STATUTE_PATTERNS:
		for m in pattern.finditer(text):
			label = m.group(0)
			out.append(
				ExtractedReference(
					reference_type="external_authority",
					matched_text=label,
					match_offset=m.start(),
					external_label=label,
				)
			)

	for m in _FRAMEWORK_PATTERN.finditer(text):
		label = m.group(0)
		out.append(
			ExtractedReference(
				reference_type="external_authority",
				matched_text=label,
				match_offset=m.start(),
				external_label=label,
				confidence=0.85,  # bare framework names are noisier than statutes
			)
		)

	return out


def _dedupe(refs: List[ExtractedReference]) -> List[ExtractedReference]:
	"""Drop duplicates within a single section.

	Two refs are considered the same if they share (reference_type,
	matched_text, match_offset). This collapses overlap when multiple regex
	patterns happen to fire on the same substring.
	"""
	seen = set()
	out: List[ExtractedReference] = []
	for r in refs:
		key = (r.reference_type, r.matched_text, r.match_offset)
		if key in seen:
			continue
		seen.add(key)
		out.append(r)
	return out


def extract_references(text: str) -> List[ExtractedReference]:
	"""Run all reference extractors against a single section's text.

	Returns a list of ExtractedReference dataclasses, deduped and sorted by
	offset. Returns an empty list if `text` is empty or no references are
	found. Never raises on well-formed input.
	"""
	if not text:
		return []

	refs: List[ExtractedReference] = []
	refs.extend(_extract_internal_section_refs(text))
	refs.extend(_extract_cross_policy_refs(text))
	refs.extend(_extract_external_authority_refs(text))

	refs = _dedupe(refs)
	refs.sort(key=lambda r: (r.match_offset, r.reference_type))
	return refs
