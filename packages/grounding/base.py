"""Faithfulness scoring interface (S1).

Mirrors IVectorRetriever / IReranker: an ABC plus a factory switch, so the
scorer can be swapped by config with graceful degradation when unavailable.

A faithfulness score answers "is this answer supported by the evidence it
cited?" — distinct from retrieval similarity, which only says "is this evidence
related to the question?". For a compliance product the first question is the
one that matters, and a benchmarked number is the defensible artifact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FaithfulnessResult:
    """A scored answer plus enough detail to audit the judgement."""

    score: float
    backend: str
    supported_claims: int = 0
    total_claims: int = 0
    unsupported: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(float(self.score), 4),
            "backend": self.backend,
            "supported_claims": self.supported_claims,
            "total_claims": self.total_claims,
            # Bound the payload: an audit record should not carry the whole answer.
            "unsupported": self.unsupported[:5],
            "detail": self.detail,
        }


class IFaithfulnessScorer(ABC):
    """Scores how well an answer is supported by its cited evidence."""

    backend = "base"

    @abstractmethod
    def score(self, *, answer: str, cited_texts: list[str]) -> FaithfulnessResult:
        """Return a 0-1 faithfulness score.

        Implementations must degrade gracefully: on any backend failure return
        a result rather than raising, so answering never hard-fails because a
        scorer was unavailable.
        """
        raise NotImplementedError


class NullFaithfulnessScorer(IFaithfulnessScorer):
    """Scores nothing. Used when verification is disabled."""

    backend = "none"

    def score(self, *, answer: str, cited_texts: list[str]) -> FaithfulnessResult:
        return FaithfulnessResult(
            score=1.0, backend=self.backend, detail={"skipped": True}
        )
