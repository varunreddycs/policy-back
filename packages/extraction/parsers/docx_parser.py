from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_HEADING_STYLE_RE = re.compile(r"^(?:heading|(?:\xfc|u)?berschrift|titre)?\s*(\d)$", re.IGNORECASE)
_ALREADY_NUMBERED_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3})*[.)]?\s")


def _heading_level(paragraph: ElementTree.Element) -> int | None:
    """Outline level from the paragraph style (Heading1..Heading9), if any."""
    style = paragraph.find("w:pPr/w:pStyle", _NS)
    if style is None:
        return None
    value = style.get(f"{{{_NS['w']}}}val") or ""
    match = _HEADING_STYLE_RE.match(value.strip().lower())
    if match:
        level = int(match.group(1))
        return level if level > 0 else None
    return None


def parse_docx(content: bytes) -> str:
    """Extract text from DOCX bytes, materializing heading numbers.

    DOCX headings usually carry no literal number — Word renders it from
    numbering.xml at display time — so the extracted text used to lose the
    document's structure entirely (S5). Headings styled Heading1..9 are
    auto-numbered here with per-level counters ("3.", "3.2") unless the text
    already starts with a number, which lets the structure-aware sectioner
    recover the real section paths.
    """
    if not content:
        return ""

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ElementTree.fromstring(xml_bytes)

    counters = [0] * 9
    lines: list[str] = []

    for paragraph in root.findall(".//w:p", _NS):
        parts = [node.text for node in paragraph.findall(".//w:t", _NS) if node.text]
        line = "".join(parts).strip()
        if not line:
            continue

        level = _heading_level(paragraph)
        if level is not None and not _ALREADY_NUMBERED_RE.match(line):
            counters[level - 1] += 1
            for deeper in range(level, 9):
                counters[deeper] = 0
            # Skip zeroed (never-seen) ancestor levels: a document that jumps
            # straight to Heading2 with no Heading1 should number "1.1", not
            # ".1", and a level skipped mid-document degrades gracefully
            # instead of leaving a gap of leading dots.
            number = ".".join(str(c) for c in counters[:level] if c > 0)
            if number:
                line = f"{number} {line}"
        if level is not None:
            # A blank line before a heading lets downstream heading detection
            # treat it as structure rather than prose.
            if lines and lines[-1] != "":
                lines.append("")

        lines.append(line)

    return "\n".join(lines)
