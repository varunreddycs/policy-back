"""Post-generation groundedness verification (S1).

Three checks run between the model's answer and the API response:

1. the answer cites evidence at all (the previously-dead citation_enforcer,
   now an enforced gate);
2. every cited handle maps to evidence that was actually supplied, and cited
   snippets verify verbatim against their source section;
3. an answer-vs-cited faithfulness score, persisted to audit_logs and able to
   drive the refusal gate.

Citations are built from what the model cited, not from retrieval ranking.
"""

from packages.grounding.base import (
    FaithfulnessResult,
    IFaithfulnessScorer,
    NullFaithfulnessScorer,
)
from packages.grounding.citations import (
    CitationCheck,
    check_citations,
    extract_handles,
    handle_for,
    is_supported_substring,
    strip_citations,
)
from packages.grounding.factory import (
    build_scorer,
    enforcement_enabled,
    faithfulness_threshold,
    verification_enabled,
)
from packages.grounding.lexical_scorer import LexicalFaithfulnessScorer

__all__ = [
    "CitationCheck",
    "FaithfulnessResult",
    "IFaithfulnessScorer",
    "LexicalFaithfulnessScorer",
    "NullFaithfulnessScorer",
    "build_scorer",
    "check_citations",
    "enforcement_enabled",
    "extract_handles",
    "faithfulness_threshold",
    "handle_for",
    "is_supported_substring",
    "strip_citations",
    "verification_enabled",
]
