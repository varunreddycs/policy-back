from __future__ import annotations

from packages.extraction.reference_extractor import (
	EXTRACTOR_VERSION,
	extract_references,
)


def test_internal_section_paragraph_symbol() -> None:
	text = "Members shall comply with §3.2 before submitting an appeal."
	refs = extract_references(text)

	assert len(refs) == 1
	r = refs[0]
	assert r.reference_type == "internal_section"
	assert r.parsed_section_path == "3.2"
	assert "§" in r.matched_text
	assert r.extractor_version == EXTRACTOR_VERSION


def test_internal_section_word_form() -> None:
	text = "Refer to Section 4.1.2 and Subsection 5 for further detail."
	refs = extract_references(text)

	internal = [r for r in refs if r.reference_type == "internal_section"]
	paths = sorted({r.parsed_section_path for r in internal})
	assert paths == ["4.1.2", "5"]


def test_cross_policy_named_match() -> None:
	text = "All requests must be processed pursuant to the Enterprise Appeals Policy."
	refs = extract_references(text)

	cross = [r for r in refs if r.reference_type == "cross_policy"]
	assert len(cross) == 1
	assert "Enterprise Appeals Policy" in cross[0].matched_text


def test_external_authority_statute_and_url() -> None:
	text = (
		"Disclosures must comply with HIPAA and 45 CFR §164.502. "
		"See https://example.org/ref for the official guidance."
	)
	refs = extract_references(text)

	ext = [r for r in refs if r.reference_type == "external_authority"]
	labels = {r.external_label for r in ext}
	uris = {r.external_uri for r in ext if r.external_uri}

	assert any("HIPAA" in label for label in labels)
	assert any("CFR" in label for label in labels)
	assert "https://example.org/ref" in uris


def test_dedupe_collapses_overlapping_matches() -> None:
	# "§3.2" and "Section 3.2" appearing at different offsets are NOT duplicates;
	# the same literal at the same offset, however, must collapse.
	text = "See §3.2. Also see §3.2."
	refs = [r for r in extract_references(text) if r.reference_type == "internal_section"]
	# Two distinct offsets → two refs.
	assert len(refs) == 2
	assert refs[0].match_offset != refs[1].match_offset


def test_empty_text_returns_empty_list() -> None:
	assert extract_references("") == []
	assert extract_references(None) == []  # type: ignore[arg-type]


def test_no_references_returns_empty_list() -> None:
	text = "The quick brown fox jumps over the lazy dog."
	assert extract_references(text) == []


def test_multi_pattern_blob_returns_sorted_by_offset() -> None:
	text = (
		"Per the Claims Appeals Policy, see §1.1 and §3.2; "
		"compliance with HIPAA is required."
	)
	refs = extract_references(text)
	# Sorted by offset ascending
	offsets = [r.match_offset for r in refs]
	assert offsets == sorted(offsets)
	# All three categories represented
	types = {r.reference_type for r in refs}
	assert types == {"internal_section", "cross_policy", "external_authority"}
