"""Dependency-free lexical faithfulness scorer (S1 default).

Not a neural entailment model: it cannot tell that "must review accounts
annually" contradicts "must review accounts monthly". What it does catch is the
failure mode that matters most here — an answer asserting specifics (numbers,
control ids, obligations) that appear nowhere in the cited evidence, which is
what fabrication actually looks like in this corpus.

It is the default because it needs no model download, no GPU and no network, so
grounding verification is always on. Swap in HHEM or an LLM judge via
FAITHFULNESS_BACKEND for a benchmarked number.
"""

from __future__ import annotations

import re

from packages.grounding.base import FaithfulnessResult, IFaithfulnessScorer
from packages.grounding.citations import (
    normalize_for_match,
    split_sentences,
    strip_citations,
)

# Tokens that carry the obligation in a compliance answer. If a claim invents
# one of these, the answer is unsupported regardless of how similar it reads.
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_CONTROL_ID_RE = re.compile(r"\b[A-Z]{2}-\d+(?:\(\d+\))?", re.IGNORECASE)

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "must",
        "not",
        "of",
        "on",
        "or",
        "shall",
        "should",
        "such",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "within",
        "would",
        "you",
        "your",
        "organization",
        "organizational",
        "system",
        "information",
        "security",
        "control",
        "controls",
        "requirement",
        "requirements",
        "policy",
        "policies",
        "section",
        "sections",
    ]
)

_MIN_CLAIM_CHARS = 25


def _content_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in normalize_for_match(text).split()
        if len(tok) > 2 and tok not in _STOPWORDS
    }


class LexicalFaithfulnessScorer(IFaithfulnessScorer):
    """Scores each claim by overlap with the cited evidence."""

    backend = "lexical"

    def __init__(
        self,
        *,
        overlap_threshold: float = 0.5,
        require_numeric_support: bool = True,
    ) -> None:
        self._overlap_threshold = overlap_threshold
        self._require_numeric_support = require_numeric_support

    def _claim_is_supported(
        self, claim: str, source_tokens: set[str], source_norm: str
    ) -> bool:
        tokens = _content_tokens(claim)
        if not tokens:
            return True  # nothing asserted

        overlap = len(tokens & source_tokens) / len(tokens)
        if overlap < self._overlap_threshold:
            return False

        if self._require_numeric_support:
            # A fabricated deadline is the classic compliance hallucination, and
            # lexical overlap alone would not catch it.
            for number in _NUMBER_RE.findall(claim):
                if number not in source_norm:
                    return False
            for control_id in _CONTROL_ID_RE.findall(claim):
                if control_id.lower() not in source_norm:
                    return False

        return True

    def score(self, *, answer: str, cited_texts: list[str]) -> FaithfulnessResult:
        prose = strip_citations(answer)
        claims = [
            s for s in split_sentences(prose) if len(s.strip()) >= _MIN_CLAIM_CHARS
        ]

        if not cited_texts:
            return FaithfulnessResult(
                score=0.0,
                backend=self.backend,
                total_claims=len(claims),
                unsupported=claims[:5],
                detail={"reason": "no_cited_evidence"},
            )
        if not claims:
            return FaithfulnessResult(
                score=1.0,
                backend=self.backend,
                detail={"reason": "no_substantive_claims"},
            )

        joined = " ".join(cited_texts)
        source_tokens = _content_tokens(joined)
        source_norm = normalize_for_match(joined)

        unsupported = [
            claim
            for claim in claims
            if not self._claim_is_supported(claim, source_tokens, source_norm)
        ]
        supported = len(claims) - len(unsupported)

        return FaithfulnessResult(
            score=supported / len(claims),
            backend=self.backend,
            supported_claims=supported,
            total_claims=len(claims),
            unsupported=unsupported,
            detail={"overlap_threshold": self._overlap_threshold},
        )
