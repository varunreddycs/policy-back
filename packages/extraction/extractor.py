from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from packages.extraction.cleaner import clean_section_text
from packages.extraction.parsers.docx_parser import parse_docx
from packages.extraction.parsers.pdf_parser import parse_pdf
from packages.extraction.parsers.txt_parser import parse_txt
from packages.extraction.sectioner import split_into_sections


@dataclass(frozen=True)
class ExtractedSection:
    section_key: str
    title: str
    start_offset: int
    end_offset: int
    text: str
    metadata: Dict[str, Any]


def extract_sections(*, filename: str, content_bytes: bytes) -> List[ExtractedSection]:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in {".txt", ".md", ".csv", ".json", ".html", ".htm"}:
        text = parse_txt(content_bytes)
    elif ext == ".docx":
        text = parse_docx(content_bytes)
    elif ext == ".pdf":
        text = parse_pdf(content_bytes)
    else:
        # Best-effort fallback for unknown formats.
        text = parse_txt(content_bytes)
    clean = clean_section_text(text)
    if not clean.strip():
        return [ExtractedSection(section_key="main", title="Main", start_offset=0, end_offset=0, text="", metadata={})]

    extractor_tag = f"ext:{ext or 'unknown'}"

    structured = split_into_sections(clean)
    if structured:
        return [
            ExtractedSection(
                section_key=section.path,
                title=section.title,
                start_offset=section.start_offset,
                end_offset=section.end_offset,
                text=section.text,
                metadata={
                    "extractor": extractor_tag,
                    "sectioning": "structured",
                    "heading_kind": section.heading_kind,
                    **section.metadata,
                },
            )
            for section in structured
        ]

    # Documents with no recognizable headings (scans-to-text, single-clause
    # memos) keep the original fixed windowing so nothing that ingested before
    # this change regresses.
    chunk_size = 4000
    results: List[ExtractedSection] = []
    for idx, start in enumerate(range(0, len(clean), chunk_size), start=1):
        end = min(len(clean), start + chunk_size)
        results.append(
            ExtractedSection(
                section_key=f"chunk-{idx}",
                title=f"Chunk {idx}",
                start_offset=start,
                end_offset=end,
                text=clean[start:end],
                metadata={
                    "extractor": extractor_tag,
                    "sectioning": "chunked",
                    "chunk_size": chunk_size,
                },
            )
        )
    return results
