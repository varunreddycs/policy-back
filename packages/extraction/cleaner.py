from __future__ import annotations

import re


_PAGE_MARKER_RE = re.compile(r"^\s*(pdf\s*page|page\s+\d+\s*(of\s*\d+)?)\b", re.IGNORECASE)
_HEADER_FOOTER_HINT_RE = re.compile(
    r"(copyright|all rights reserved|confidential|department of|policy platform)",
    re.IGNORECASE,
)


def clean_section_text(text: str) -> str:
    """Normalize extracted section text by removing common document artifacts."""
    if not text:
        return ""

    # Normalize line endings and trim leading/trailing empty lines.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    # Drop obvious PDF/page marker lines and collapse duplicate headers/footers.
    lines = [line.strip() for line in normalized.split("\n")]
    kept: list[str] = []
    seen_artifact_lines: set[str] = set()

    for line in lines:
        if not line:
            kept.append("")
            continue

        if _PAGE_MARKER_RE.search(line):
            continue

        lowered = line.lower()
        # Heuristic: frequently repeated short administrative lines are usually headers/footers.
        if len(line) <= 80 and _HEADER_FOOTER_HINT_RE.search(line):
            if lowered in seen_artifact_lines:
                continue
            seen_artifact_lines.add(lowered)

        kept.append(line)

    # Remove repeated consecutive identical lines.
    deduped: list[str] = []
    previous = None
    for line in kept:
        if line and previous == line:
            continue
        deduped.append(line)
        previous = line if line else previous

    # Collapse excessive blank lines and whitespace.
    merged = "\n".join(deduped)
    merged = re.sub(r"[ \t]+", " ", merged)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip()
