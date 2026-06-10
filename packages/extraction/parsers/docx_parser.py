from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree


def parse_docx(content: bytes) -> str:
    """Extract plain text from DOCX bytes.

    DOCX files are ZIP archives; the main body text is in word/document.xml.
    """
    if not content:
        return ""

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ElementTree.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        parts: list[str] = []
        for text_node in paragraph.findall(".//w:t", ns):
            if text_node.text:
                parts.append(text_node.text)
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)

    return "\n".join(paragraphs)
