from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

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
    # Phase 1: only TXT parsing is implemented; other formats are stubs.
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
                metadata={"extractor": "stub", "chunk_size": chunk_size},
            )
        )
    return results
