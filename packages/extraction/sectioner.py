"""Structure-aware sectioning (S5).

Replaces fixed 4000-char ``chunk-N`` windowing with heading-aware sections that
carry a real dotted ``section_path`` ("3.2", "AC-2(3)") and heading text.

Why it matters: citations previously pointed at "Chunk 3", which no auditor can
look up, and the reference resolver's dotted-path matcher could never match a
chunk label — the "intentionally low" resolution rate was a data-model
disconnect, not a tuning problem. Real paths unlock S3 (crosswalk graph) and S4
(conflict detection between identified clauses).

Documents with no recognizable structure fall back to the old chunking, so
nothing that ingested before regresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# A section that exceeds this is split into parts; retrieval and the LLM
# evidence window were tuned for ~4000-char texts and oversized sections would
# regress them.
MAX_SECTION_CHARS = 4000

# Headings that carry their own number: "3.", "3.2", "3.2.1 Title".
_DOTTED_HEADING_RE = re.compile(r"^(?P<num>\d{1,3}(?:\.\d{1,3}){0,5})[.)]?\s+(?P<title>\S.*)?$")
# NIST-style control heading: "AC-2 Account Management", "AC-2(3) Disable Accounts".
# The title class allows internal/trailing periods ("Account Mgmt. Policy")
# without opening the door to arbitrary prose — the overall length cap plus
# the module-level 120-char line cap keep long sentences out.
_CONTROL_HEADING_RE = re.compile(
    r"^(?P<id>[A-Z]{2}-\d{1,3}(?:\(\d+\))?)\s+(?P<title>[A-Z][A-Za-z0-9 ,&/'.\-()]{2,80})$"
)
# "Section 4:", "Article IV -", "Appendix A". A real delimiter (colon, period,
# dash, or end-of-line) is required after the number so a bare space can't
# stand in for one — otherwise inline cross-references like "Section 5 of the
# Ohio Revised Code applies..." are misread as headings.
_NAMED_HEADING_RE = re.compile(
    r"^(?P<kind>section|article|appendix|part|chapter)\s+(?P<num>[0-9]{1,3}|[IVXLC]{1,7}|[A-Z])\b(?:\s*[:.\-]\s*(?P<title>.*)|\s*)$",
    re.IGNORECASE,
)
# Short ALL-CAPS lines are headings in most policy documents.
_ALLCAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 ,&/\-()]{3,60}$")
# Single shouted callout words are emphasis, not structure.
_ALLCAPS_CALLOUT_BLACKLIST = frozenset(
    {"NOTE", "WARNING", "CAUTION", "IMPORTANT", "EXAMPLE", "DISCLAIMER", "NOTICE"}
)
# Canonical one-word policy headings are legitimate despite being single
# words; anything else single-word is treated as a callout (see blacklist
# above) since a lone shouted word is far more often emphasis than structure.
_ALLCAPS_SINGLE_WORD_ALLOWLIST = frozenset(
    {
        "PURPOSE",
        "SCOPE",
        "DEFINITIONS",
        "POLICY",
        "PROCEDURE",
        "BACKGROUND",
        "REFERENCES",
        "APPLICABILITY",
        "ENFORCEMENT",
        "RESPONSIBILITIES",
    }
)
# Modal/imperative words mark an allcaps line as a shouted sentence
# ("ALL EMPLOYEES MUST COMPLY WITH THIS") rather than a noun-phrase heading
# ("PURPOSE AND SCOPE", "HIPAA COMPLIANCE").
_ALLCAPS_SENTENCE_WORDS = frozenset({"MUST", "SHALL", "SHOULD", "WILL", "MAY", "NOT", "COMPLY"})

_BULLET_PREFIX_RE = re.compile(r"^[-*•●▪]\s")


@dataclass(slots=True)
class Section:
    """One structural unit of a document."""

    path: str
    title: str
    text: str
    start_offset: int
    end_offset: int
    heading_kind: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Heading:
    line_index: int
    path: str
    title: str
    kind: str


def _classify_heading(line: str, previous_blank: bool) -> tuple[str, str, str] | None:
    """Return (path, title, kind) when the line is a heading, else None."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120 or _BULLET_PREFIX_RE.match(stripped):
        return None

    match = _CONTROL_HEADING_RE.match(stripped)
    if match:
        return match.group("id"), stripped, "control"

    match = _DOTTED_HEADING_RE.match(stripped)
    if match:
        num = match.group("num")
        title = (match.group("title") or "").strip()
        # "3.2 Something" is a heading; "3.2 mg of..." mid-paragraph is not.
        # Requiring a title that starts with an uppercase letter, has no
        # trailing sentence punctuation, and is short (a heading, not a
        # sentence) keeps prose and numbered-list items out.
        words = title.split()
        if (
            title
            and title[0].isupper()
            and not title.endswith((".", ";", ","))
            and len(words) <= 6
        ):
            # A dotted multi-level number ("4.1.2") is unambiguous structure
            # on its own. A bare number ("1.", "2)") is indistinguishable from
            # an ordinary numbered list item, so it additionally needs
            # previous_blank and a very short, title-cased fragment (not a
            # full sentence) to count as a heading.
            if "." in num:
                return num, title, "dotted"
            if (
                previous_blank
                and len(words) <= 2
                and all(word[0].isupper() for word in words if word[0].isalpha())
            ):
                return num, title, "dotted"
        return None

    match = _NAMED_HEADING_RE.match(stripped)
    if match:
        label = f"{match.group('kind').title()} {match.group('num')}"
        title = (match.group("title") or "").strip() or label
        return label, title, "named"

    # ALL-CAPS only counts after a blank line: mid-paragraph shouting
    # ("MUST NOT") is not a heading.
    if previous_blank and _ALLCAPS_HEADING_RE.match(stripped) and len(stripped.split()) <= 8:
        words = stripped.split()
        # Modal/imperative words mean this is a shouted sentence, not a title.
        if _ALLCAPS_SENTENCE_WORDS & set(words):
            return None
        if len(words) == 1:
            if stripped not in _ALLCAPS_SINGLE_WORD_ALLOWLIST:
                return None
        elif stripped in _ALLCAPS_CALLOUT_BLACKLIST:
            return None
        # Preserve the original casing: .title() would mangle acronyms like
        # "HIPAA" or "IT" into "Hipaa" / "It", corrupting citation labels.
        return stripped, stripped, "allcaps"

    return None


def _find_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    previous_blank = True
    for index, line in enumerate(lines):
        found = _classify_heading(line, previous_blank)
        if found:
            path, title, kind = found
            headings.append(_Heading(index, path, title, kind))
        previous_blank = not line.strip()
    return headings


def _split_oversized(section: Section) -> list[Section]:
    if len(section.text) <= MAX_SECTION_CHARS:
        return [section]
    parts: list[Section] = []
    text = section.text
    for part_index, start in enumerate(range(0, len(text), MAX_SECTION_CHARS), start=1):
        chunk = text[start : start + MAX_SECTION_CHARS]
        # Every part keeps the parent's dotted path unchanged so citations and
        # the reference resolver's token-bounded path matcher still land on
        # the real clause; the part number is storage-only and lives in
        # metadata instead of polluting section_path (see D9).
        parts.append(
            Section(
                path=section.path,
                title=section.title,
                text=chunk,
                start_offset=section.start_offset + start,
                end_offset=section.start_offset + start + len(chunk),
                heading_kind=section.heading_kind,
                metadata={**section.metadata, "part": part_index},
            )
        )
    return parts


def split_into_sections(text: str) -> list[Section]:
    """Split cleaned document text into heading-delimited sections.

    Returns an empty list when the text has no usable structure (fewer than two
    recognizable headings) — the caller decides the fallback, keeping this
    module free of chunking policy.
    """
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    headings = _find_headings(lines)
    # One heading is indistinguishable from a title page; structure means
    # the document actually navigates by headings.
    if len(headings) < 2:
        return []

    # Character offset of each line start.
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    sections: list[Section] = []

    # Preamble before the first heading keeps its content addressable.
    first = headings[0]
    preamble = "\n".join(lines[: first.line_index]).strip()
    if preamble:
        sections.append(
            Section(
                path="preamble",
                title="Preamble",
                text=preamble,
                start_offset=0,
                end_offset=len(preamble),
                heading_kind="none",
            )
        )

    for position, heading in enumerate(headings):
        end_line = (
            headings[position + 1].line_index
            if position + 1 < len(headings)
            else len(lines)
        )
        body = "\n".join(lines[heading.line_index : end_line]).strip()
        if not body:
            continue
        start = offsets[heading.line_index]
        sections.append(
            Section(
                path=heading.path,
                title=heading.title,
                text=body,
                start_offset=start,
                end_offset=start + len(body),
                heading_kind=heading.kind,
            )
        )

    # Duplicate paths (same clause number reused) get a disambiguating
    # ordinal, but it stays in metadata rather than mutating section.path
    # (see D9) — the worker derives storage uniqueness from section_index, and
    # a clean path keeps the reference resolver's token-bounded path matcher
    # from matching "3.2", "3.2~2", etc. as if they were different clauses.
    seen: dict[str, int] = {}
    for section in sections:
        count = seen.get(section.path, 0)
        seen[section.path] = count + 1
        if count:
            section.metadata = {**section.metadata, "duplicate_ordinal": count + 1}

    result: list[Section] = []
    for section in sections:
        result.extend(_split_oversized(section))
    return result
