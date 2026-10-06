"""FAITHFULNESS_BACKEND switch (S1), mirroring the retrieval/reranking factories."""

from __future__ import annotations

import logging
import os

from packages.grounding.base import IFaithfulnessScorer, NullFaithfulnessScorer
from packages.grounding.lexical_scorer import LexicalFaithfulnessScorer

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUTHY


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def verification_enabled() -> bool:
    """Whether grounding checks run at all."""
    return _env_bool("GROUNDEDNESS_VERIFY", True)


def enforcement_enabled() -> bool:
    """Whether a failed grounding check refuses the answer.

    Separate from verification so the checks can be measured in report-only
    mode before they are allowed to change what users see.
    """
    return _env_bool("GROUNDEDNESS_ENFORCE", True)


def faithfulness_threshold() -> float:
    return _env_float("GROUNDEDNESS_MIN_SCORE", 0.6)


def build_scorer() -> IFaithfulnessScorer:
    """Build the configured scorer; unknown or unavailable degrades to lexical."""
    if not verification_enabled():
        return NullFaithfulnessScorer()

    backend = os.getenv("FAITHFULNESS_BACKEND", "lexical").strip().lower()

    if backend in {"", "lexical", "default"}:
        return LexicalFaithfulnessScorer()

    if backend in {"none", "off"}:
        return NullFaithfulnessScorer()

    if backend == "hhem":
        from packages.grounding.model_scorers import HhemFaithfulnessScorer

        scorer = HhemFaithfulnessScorer()
        if not scorer.available:
            logger.warning(
                "grounding.backend.unavailable",
                extra={"backend": backend, "reason": "transformers not installed"},
            )
            return LexicalFaithfulnessScorer()
        return scorer

    if backend in {"azure", "azure_judge", "llm"}:
        from packages.grounding.model_scorers import AzureJudgeFaithfulnessScorer

        scorer = AzureJudgeFaithfulnessScorer()
        if not scorer.available:
            logger.warning(
                "grounding.backend.unavailable",
                extra={"backend": backend, "reason": "no chat deployment"},
            )
            return LexicalFaithfulnessScorer()
        return scorer

    logger.warning("grounding.backend.unknown", extra={"backend": backend})
    return LexicalFaithfulnessScorer()
