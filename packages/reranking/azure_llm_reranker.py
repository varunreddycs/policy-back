"""Azure OpenAI LLM-scored reranker (Q4).

Cohere and Voyage are the purpose-built cross-encoders, but both are paid
third-party APIs. This backend reuses the Azure OpenAI chat deployment the
platform already has, so a reranking stage can run on existing credentials with
no new vendor egress — which also matters for gov/compliance buyers with data
residency constraints.

It asks the model to score each candidate's relevance 0-10 in a single call and
returns a JSON array, rather than one call per candidate.
"""

from __future__ import annotations

import json
import logging
import re

from packages.core.dtos import EvidenceCandidate
from packages.llm.client import LlmClient, LlmError
from packages.reranking.base import IReranker

logger = logging.getLogger(__name__)

_MAX_DOC_CHARS = 1200

_SYSTEM_PROMPT = (
    "You score how well each numbered policy excerpt answers the user's question.\n\n"
    "Rules:\n"
    "1) Score each excerpt 0-10: 10 = directly states the answer, "
    "5 = related topic but does not answer, 0 = irrelevant.\n"
    "2) Judge relevance to the question ONLY. Ignore which department or "
    "organization the excerpt belongs to.\n"
    "3) Reply with ONLY a JSON array of objects: "
    '[{"index": 1, "score": 8}, {"index": 2, "score": 3}]\n'
    "4) Include every excerpt exactly once. No prose, no markdown fences."
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class AzureLlmReranker(IReranker):
    """Rerank by asking the existing Azure OpenAI deployment to score relevance."""

    provider = "azure_llm"

    def __init__(self, *, llm: LlmClient | None = None) -> None:
        self._llm = llm or LlmClient()

    @property
    def available(self) -> bool:
        return self._llm.available

    @staticmethod
    def _build_prompt(query: str, candidates: list[EvidenceCandidate]) -> str:
        lines = [f"Question: {query}", "", "Excerpts:"]
        for i, candidate in enumerate(candidates, start=1):
            text = (candidate.text or "").strip().replace("\n", " ")[:_MAX_DOC_CHARS]
            lines.append(f"[{i}] {text}")
        lines.append("")
        lines.append(f"Score all {len(candidates)} excerpts as a JSON array.")
        return "\n".join(lines)

    @staticmethod
    def _parse_scores(raw: str, expected: int) -> dict[int, float]:
        """Extract {1-based index: score}. Tolerates fences and stray prose."""
        match = _JSON_ARRAY_RE.search(raw or "")
        if not match:
            return {}
        try:
            rows = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        if not isinstance(rows, list):
            return {}

        scores: dict[int, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = row.get("index")
            score = row.get("score")
            if (
                isinstance(index, int)
                and isinstance(score, (int, float))
                and 1 <= index <= expected
            ):
                scores[index] = float(score)
        return scores

    def rerank(
        self,
        *,
        query: str,
        candidates: list[EvidenceCandidate],
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        limit = max(1, int(top_k))
        if len(candidates) <= 1 or not self.available:
            return candidates[:limit]

        try:
            raw = self._llm.complete(
                _SYSTEM_PROMPT, self._build_prompt(query, candidates)
            )
        except LlmError as exc:
            logger.warning("rerank.llm.failed", extra={"error": str(exc)})
            return candidates[:limit]

        scores = self._parse_scores(raw, len(candidates))
        if not scores:
            logger.warning("rerank.llm.unparseable_scores")
            return candidates[:limit]

        scored: list[tuple[float, int, EvidenceCandidate]] = []
        for position, candidate in enumerate(candidates):
            score = scores.get(position + 1)
            if score is None:
                # Unscored candidates keep their fused position rather than
                # being dropped — a partial LLM reply must not lose evidence.
                score = -1.0
            scored.append((score, position, candidate))

        # Sort by score desc, then original position asc so ties stay stable.
        scored.sort(key=lambda row: (-row[0], row[1]))

        reordered: list[EvidenceCandidate] = []
        for score, position, candidate in scored:
            md = dict(candidate.metadata or {})
            md["rerank_provider"] = self.provider
            md["pre_rerank_score"] = float(candidate.score or 0.0)
            md["pre_rerank_position"] = position
            if score >= 0:
                md["rerank_score"] = score / 10.0
            reordered.append(candidate.model_copy(update={"metadata": md}))

        return reordered[:limit]
