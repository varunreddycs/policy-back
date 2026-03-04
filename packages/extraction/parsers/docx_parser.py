from __future__ import annotations

from packages.core.errors import NotImplementedFeature


def parse_docx(_: bytes) -> str:
    raise NotImplementedFeature("DOCX parsing not implemented yet")
