from __future__ import annotations

import pytest

from packages.rag.citation_enforcer import MissingCitations, ensure_citations


def test_ensure_citations_raises_when_missing() -> None:
	with pytest.raises(MissingCitations):
		ensure_citations("No citations here")


def test_ensure_citations_allows_when_present() -> None:
	ensure_citations("Answer... [policy_version_id=123]")
