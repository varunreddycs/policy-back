from __future__ import annotations

import io


def parse_pdf(content: bytes) -> str:
    if not content:
        return ""

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PDF parsing requires 'pypdf' dependency") from exc

    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")

    return "\n".join([text for text in pages if text])
