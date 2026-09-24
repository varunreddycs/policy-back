"""S5: structure-aware sectioning — regression locks for sectioner.py,
the structured path in extractor.py, and the docx heading-numbering that
feeds it.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest

from packages.extraction.extractor import extract_sections
from packages.extraction.parsers.docx_parser import _NS, _heading_level, parse_docx
from packages.extraction.sectioner import (
    MAX_SECTION_CHARS,
    _classify_heading,
    split_into_sections,
)

# ---------------------------------------------------------------------------
# A. _classify_heading positives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected_path", "expected_kind"),
    [
        ("3.2 Access Control", "3.2", "dotted"),
        ("4. Retention", "4", "dotted"),
        ("2. Eligibility", "2", "dotted"),
        ("4.1.2 Records Retention Schedule", "4.1.2", "dotted"),
        ("Section 4: Enforcement", "Section 4", "named"),
        ("Article IV - Governance", "Article IV", "named"),
        ("Appendix A", "Appendix A", "named"),
        ("PURPOSE AND SCOPE", "PURPOSE AND SCOPE", "allcaps"),
        ("HIPAA COMPLIANCE", "HIPAA COMPLIANCE", "allcaps"),
        ("AC-2 Account Management", "AC-2", "control"),
        ("AC-2(3) Disable Accounts", "AC-2(3)", "control"),
        ("AC-2 Account Management.", "AC-2", "control"),
    ],
)
def test_classify_heading_detects_structure(
    line: str, expected_path: str, expected_kind: str
) -> None:
    result = _classify_heading(line, True)
    assert result is not None
    path, _title, kind = result
    assert path == expected_path
    assert kind == expected_kind


# ---------------------------------------------------------------------------
# B. _classify_heading negatives — regression-critical: prose that looks like
# a heading (numbered sentences, inline cross-references, shouted sentences)
# must NOT be misread as structure.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "1. The following applies to all staff members",
        "1. Submit the form",
        "1) Complete the training",
        "1 The employee must submit a request",
        "2.5 percent of salary is withheld",
        "3.2 mg per dose",
        "4.1.2 employees may request",
        "Section 5 of the Ohio Revised Code applies to state employees.",
        "Part 2 of this policy is superseded by the newer one",
        "NOTE",
        "MUST NOT",
        "WARNING",
        "ALL EMPLOYEES MUST COMPLY WITH THIS",
    ],
)
def test_classify_heading_rejects_prose(line: str) -> None:
    assert _classify_heading(line, True) is None


# ---------------------------------------------------------------------------
# C. Acronym preservation — .title() would corrupt "HIPAA" into "Hipaa" and
# break citation labels.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["HIPAA COMPLIANCE", "IT SECURITY & BYOD", "PTO / FMLA LEAVE"],
)
def test_classify_heading_preserves_acronym_casing(line: str) -> None:
    result = _classify_heading(line, True)
    assert result is not None
    path, title, _kind = result
    assert path == line
    assert title == line


# ---------------------------------------------------------------------------
# D. Phantom-section regression — the most important test in this file.
#
# A phantom section both truncates real content (the split point lands mid-
# clause) and gives the reference resolver's dotted-path matcher a fragment
# to resolve genuine references against instead of the real section. Inline
# cross-references ("1. Submit form...", "Section 5 of the Ohio Revised
# Code...") must be recognized as prose, not new headings.
# ---------------------------------------------------------------------------


def test_split_into_sections_does_not_create_phantom_sections_from_inline_refs() -> None:
    doc = (
        "2. Eligibility\n"
        "\n"
        "Employees are eligible after 90 days of service. The following apply:\n"
        "\n"
        "1. Submit form TR-1 before travel.\n"
        "\n"
        "Section 5 of the Ohio Revised Code applies to state employees.\n"
        "\n"
        "3. Reimbursement\n"
        "\n"
        "Submit receipts within 30 days."
    )

    sections = split_into_sections(doc)

    assert [s.path for s in sections] == ["2", "3"]
    assert "TR-1" in sections[0].text


# ---------------------------------------------------------------------------
# E. Offset round-trip — every section's stored text must be exactly
# recoverable by slicing the original document with its own offsets,
# including the preamble.
# ---------------------------------------------------------------------------


def test_offsets_round_trip_for_every_section_including_preamble() -> None:
    doc = (
        "This is a preamble line before any structure.\n"
        "It spans a couple of lines.\n"
        "\n"
        "1. Purpose\n"
        "\n"
        "This section explains purpose.\n"
        "\n"
        "2. Scope\n"
        "\n"
        "This section explains scope.\n"
        "\n"
        "3. Enforcement\n"
        "\n"
        "Violations are handled per HR policy."
    )

    sections = split_into_sections(doc)

    assert [s.path for s in sections] == ["preamble", "1", "2", "3"]
    for section in sections:
        assert doc[section.start_offset : section.end_offset] == section.text


# ---------------------------------------------------------------------------
# F. section_path cleanliness (D9 regression) — oversized-section parts and
# duplicate clause numbers must not mutate section_path; storage-only detail
# lives in metadata so the reference resolver's path matcher stays exact.
# ---------------------------------------------------------------------------


def test_oversized_section_parts_keep_clean_path_and_tile_the_parent() -> None:
    body = "x" * (MAX_SECTION_CHARS * 2 + 500)
    doc = f"1. Big Section\n\n{body}\n\n2. Small Section\n\nSmall body text here."

    sections = split_into_sections(doc)
    parts = [s for s in sections if s.path == "1"]

    assert len(parts) == 3
    assert all(s.path == "1" for s in parts)
    assert [s.metadata["part"] for s in parts] == [1, 2, 3]

    for earlier, later in zip(parts, parts[1:]):
        assert earlier.end_offset == later.start_offset

    assert parts[0].start_offset == 0
    assert parts[-1].end_offset - parts[0].start_offset == len("".join(p.text for p in parts))
    assert "".join(p.text for p in parts) == doc[parts[0].start_offset : parts[-1].end_offset]


def test_duplicate_section_paths_keep_clean_path_with_ordinal_in_metadata() -> None:
    doc = (
        "1. Purpose\n"
        "\n"
        "First occurrence of clause one.\n"
        "\n"
        "2. Scope\n"
        "\n"
        "Scope text here.\n"
        "\n"
        "1. Purpose\n"
        "\n"
        "Second occurrence of clause one, reused number."
    )

    sections = split_into_sections(doc)
    ones = [s for s in sections if s.path == "1"]

    assert len(ones) == 2
    assert "duplicate_ordinal" not in ones[0].metadata
    assert ones[1].metadata["duplicate_ordinal"] == 2


def test_no_section_path_contains_hash_or_tilde_markers() -> None:
    body = "x" * (MAX_SECTION_CHARS * 2 + 500)
    doc = (
        f"1. Big Section\n\n{body}\n\n"
        "2. Repeated\n\nFirst.\n\n"
        "2. Repeated\n\nSecond."
    )

    sections = split_into_sections(doc)

    assert sections
    assert all("#" not in s.path and "~" not in s.path for s in sections)


# ---------------------------------------------------------------------------
# G. Fallback guard — no usable structure means the caller decides chunking,
# not this module.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\n  ",
        "Just some prose.\nNo headings at all here.\nMore prose.",
        "1. Purpose\n\nOnly one heading in this whole document, nothing else structural.",
    ],
)
def test_split_into_sections_returns_empty_without_real_structure(text: str) -> None:
    assert split_into_sections(text) == []


# ---------------------------------------------------------------------------
# H. extractor.py integration
# ---------------------------------------------------------------------------


def test_extract_sections_uses_real_paths_for_structured_documents() -> None:
    doc = (
        "1. Purpose\n"
        "\n"
        "This policy establishes rules.\n"
        "\n"
        "2. Scope\n"
        "\n"
        "Applies to all staff.\n"
        "\n"
        "AC-2 Account Management\n"
        "\n"
        "Accounts must be reviewed quarterly."
    ).encode()

    sections = extract_sections(filename="policy.txt", content_bytes=doc)

    assert [s.section_key for s in sections] == ["1", "2", "AC-2"]
    for section in sections:
        assert section.metadata["sectioning"] == "structured"
        assert "heading_kind" in section.metadata


def test_extract_sections_falls_back_to_chunking_without_structure() -> None:
    prose = ("This is a long unstructured document. " * 300).encode()

    sections = extract_sections(filename="memo.txt", content_bytes=prose)

    assert sections
    assert all(s.section_key.startswith("chunk-") for s in sections)
    for section in sections:
        assert section.metadata["sectioning"] == "chunked"
        assert section.metadata["chunk_size"] == 4000


def test_extract_sections_empty_document_returns_single_main_section() -> None:
    """The worker depends on this exact shape to detect zero-text and park
    the version in needs_review — do not change it.
    """
    sections = extract_sections(filename="empty.txt", content_bytes=b"")

    assert len(sections) == 1
    assert sections[0].section_key == "main"


# ---------------------------------------------------------------------------
# I. docx _heading_level style table.
#
# "Heading 1" (with a space) was a silent total-failure bug: an earlier regex
# only matched "HeadingN" with no separator, so space-separated Word styles
# (common when a template author renames styles) numbered nothing and the
# sectioner saw a flat, unstructured document. This table pins every style
# variant the regex must (and must not) recognize.
# ---------------------------------------------------------------------------


def _make_paragraph(style_val: str | None) -> ElementTree.Element:
    namespace = _NS["w"]
    xml = f'<w:p xmlns:w="{namespace}">'
    if style_val is not None:
        xml += f'<w:pPr><w:pStyle w:val="{style_val}"/></w:pPr>'
    xml += "<w:r><w:t>text</w:t></w:r></w:p>"
    return ElementTree.fromstring(xml)


@pytest.mark.parametrize(
    ("style_val", "expected_level"),
    [
        ("Heading1", 1),
        ("Heading 1", 1),
        ("heading1", 1),
        ("Heading9", 9),
        ("Überschrift1", 1),
        ("Überschrift 2", 2),
        ("berschrift1", 1),
        ("Titre1", 1),
        ("Normal", None),
        ("ListParagraph", None),
        ("Title", None),
        ("TOC1", None),
        ("Heading10", None),
        ("Heading2Char", None),
    ],
)
def test_heading_level_style_table(style_val: str, expected_level: int | None) -> None:
    paragraph = _make_paragraph(style_val)
    assert _heading_level(paragraph) == expected_level


def test_heading_level_returns_none_without_pstyle() -> None:
    paragraph = _make_paragraph(None)
    assert _heading_level(paragraph) is None


# ---------------------------------------------------------------------------
# J. docx counter sequence — end-to-end through parse_docx on an in-memory
# minimal .docx (a zipfile containing only word/document.xml).
# ---------------------------------------------------------------------------


def _paragraph_xml(text: str, style: str | None = None) -> str:
    namespace = _NS["w"]
    xml = f'<w:p xmlns:w="{namespace}">'
    if style is not None:
        xml += f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    xml += f"<w:r><w:t>{text}</w:t></w:r></w:p>"
    return xml


def _make_docx_bytes(paragraph_styles: list[tuple[str, str | None]]) -> bytes:
    namespace = _NS["w"]
    body = "".join(_paragraph_xml(text, style) for text, style in paragraph_styles)
    document_xml = (
        f'<?xml version="1.0"?><w:document xmlns:w="{namespace}">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_parse_docx_numbers_headings_by_outline_level() -> None:
    content = _make_docx_bytes(
        [
            ("First", "Heading1"),
            ("Second", "Heading2"),
            ("Third", "Heading2"),
            ("Fourth", "Heading1"),
            ("Fifth", "Heading2"),
        ]
    )

    text = parse_docx(content)

    assert "1 First" in text
    assert "1.1 Second" in text
    assert "1.2 Third" in text
    assert "2 Fourth" in text
    assert "2.1 Fifth" in text


def test_parse_docx_starting_at_h2_has_no_leading_dot() -> None:
    content = _make_docx_bytes(
        [
            ("Alpha", "Heading2"),
            ("Beta", "Heading3"),
            ("Gamma", "Heading3"),
        ]
    )

    text = parse_docx(content)

    lines = [line for line in text.split("\n") if line]
    assert lines == ["1 Alpha", "1.1 Beta", "1.2 Gamma"]


def test_parse_docx_does_not_double_number_already_numbered_heading() -> None:
    content = _make_docx_bytes([("3.2 Eligibility", "Heading1")])

    text = parse_docx(content)

    assert text == "3.2 Eligibility"
