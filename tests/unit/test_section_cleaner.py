from __future__ import annotations

from packages.extraction.cleaner import clean_section_text


def test_clean_section_text_removes_pdf_page_markers_and_repeated_headers() -> None:
    raw = """
    PDF PAGE 1
    Department of Operations
    Important guidance text line 1.

    Department of Operations
    PAGE 2 OF 5
    Important guidance text line 2.
    """

    cleaned = clean_section_text(raw)

    assert "PDF PAGE" not in cleaned.upper()
    assert "PAGE 2 OF 5" not in cleaned.upper()
    assert cleaned.count("Department of Operations") == 1
    assert "Important guidance text line 1." in cleaned
    assert "Important guidance text line 2." in cleaned


def test_clean_section_text_collapses_whitespace() -> None:
    raw = "Line   one\n\n\nLine\t\ttwo"
    cleaned = clean_section_text(raw)
    assert cleaned == "Line one\n\nLine two"
