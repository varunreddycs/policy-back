from __future__ import annotations

from packages.core.errors import NotImplementedFeature


def parse_pdf(_: bytes) -> str:
    raise NotImplementedFeature("PDF parsing not implemented yet")
