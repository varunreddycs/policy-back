from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from packages.extraction.parsers.docx_parser import parse_docx
from packages.extraction.parsers.pdf_parser import parse_pdf
from packages.extraction.parsers.txt_parser import parse_txt


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
    if not text.strip():
        return [ExtractedSection(section_key="main", title="Main", start_offset=0, end_offset=0, text="", metadata={})]

    chunk_size = 4000
    results: List[ExtractedSection] = []
    clean = text.strip()
    for idx, start in enumerate(range(0, len(clean), chunk_size), start=1):
        end = min(len(clean), start + chunk_size)
        results.append(
            ExtractedSection(
                section_key=f"chunk-{idx}",
                title=f"Chunk {idx}",
                start_offset=start,
                end_offset=end,
                text=clean[start:end],
                metadata={"extractor": f"ext:{ext or 'unknown'}", "chunk_size": chunk_size},
            )
        )
    return results
