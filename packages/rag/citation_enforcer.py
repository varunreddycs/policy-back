from __future__ import annotations

from packages.core.errors import DomainError


class MissingCitations(DomainError):
    def __init__(self) -> None:
        super().__init__(code="MISSING_CITATIONS", message="Answer missing citations")


def ensure_citations(answer: str) -> None:
    # Template hook for strict citation enforcement.
    if not answer or "[policy_version_id=" not in answer:
        raise MissingCitations()
