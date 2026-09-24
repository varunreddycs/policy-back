"""Optional model-backed faithfulness scorers (S1).

Neither is a hard dependency. HHEM needs torch + transformers (~2GB in the
image); the Azure judge needs a configured chat deployment and costs a second
LLM call per answer. Both fall back to the lexical scorer when unavailable, so
selecting one can never leave answering without a grounding check.
"""

from __future__ import annotations

import json
import logging
import os
import re

from packages.grounding.base import FaithfulnessResult, IFaithfulnessScorer
from packages.grounding.citations import split_sentences, strip_citations
from packages.grounding.lexical_scorer import LexicalFaithfulnessScorer

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class HhemFaithfulnessScorer(IFaithfulnessScorer):
    """Vectara HHEM-2.1-open, a purpose-built hallucination detector.

    Loads lazily so importing this module never pulls in torch. The model is a
    cross-encoder scoring (premise=evidence, hypothesis=claim) in [0, 1].
    """

    backend = "hhem"

    def __init__(self, *, model_name: str | None = None) -> None:
        self._model_name = model_name or os.getenv(
            "HHEM_MODEL", "vectara/hallucination_evaluation_model"
        )
        self._model = None
        self._fallback = LexicalFaithfulnessScorer()

    @property
    def available(self) -> bool:
        try:
            import transformers  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            from transformers import (  # type: ignore[import-not-found]
                AutoModelForSequenceClassification,
            )

            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._model_name, trust_remote_code=True
            )
        return self._model

    def score(self, *, answer: str, cited_texts: list[str]) -> FaithfulnessResult:
        if not cited_texts:
            return FaithfulnessResult(
                score=0.0, backend=self.backend, detail={"reason": "no_cited_evidence"}
            )

        prose = strip_citations(answer)
        claims = [s for s in split_sentences(prose) if len(s.strip()) >= 25]
        if not claims:
            return FaithfulnessResult(
                score=1.0,
                backend=self.backend,
                detail={"reason": "no_substantive_claims"},
            )

        premise = " ".join(cited_texts)
        try:
            model = self._load()
            pairs = [(premise, claim) for claim in claims]
            scores = [float(s) for s in model.predict(pairs)]
        except Exception as exc:  # noqa: BLE001 - torch/transformers can raise anything
            # A missing or broken model must never break answering; log and degrade.
            logger.warning(
                "grounding.hhem.failed",
                extra={"error": str(exc), "model": self._model_name},
            )
            result = self._fallback.score(answer=answer, cited_texts=cited_texts)
            result.detail["hhem_error"] = str(exc)[:200]
            return result

        threshold = float(os.getenv("HHEM_CLAIM_THRESHOLD", "0.5") or "0.5")
        unsupported = [c for c, s in zip(claims, scores, strict=False) if s < threshold]
        supported = len(claims) - len(unsupported)

        return FaithfulnessResult(
            score=sum(scores) / len(scores),
            backend=self.backend,
            supported_claims=supported,
            total_claims=len(claims),
            unsupported=unsupported,
            detail={"model": self._model_name, "claim_threshold": threshold},
        )


class AzureJudgeFaithfulnessScorer(IFaithfulnessScorer):
    """Score faithfulness with the existing Azure OpenAI chat deployment.

    Not self-hosted, so it is not the moat the story describes — but it needs
    no new dependency and is useful for comparison against the lexical default.
    """

    backend = "azure_judge"

    _SYSTEM = (
        "You verify whether an answer is supported by the evidence it cites.\n\n"
        "Rules:\n"
        "1) Consider ONLY the evidence given. Outside knowledge is irrelevant.\n"
        "2) A claim is supported only if the evidence states or directly implies it.\n"
        "3) Numbers, deadlines and control identifiers must match the evidence exactly.\n"
        '4) Reply with ONLY JSON: {"supported": <int>, "total": <int>, '
        '"unsupported": ["<claim>", ...]}\n'
        "5) No prose, no markdown fences."
    )

    def __init__(self, *, llm=None) -> None:
        from packages.llm.client import LlmClient

        self._llm = llm or LlmClient()
        self._fallback = LexicalFaithfulnessScorer()

    @property
    def available(self) -> bool:
        return bool(self._llm.available)

    def score(self, *, answer: str, cited_texts: list[str]) -> FaithfulnessResult:
        from packages.llm.client import LlmError

        if not cited_texts:
            return FaithfulnessResult(
                score=0.0, backend=self.backend, detail={"reason": "no_cited_evidence"}
            )
        if not self.available:
            return self._fallback.score(answer=answer, cited_texts=cited_texts)

        evidence = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(cited_texts, start=1))
        user = f"Evidence:\n{evidence}\n\nAnswer:\n{strip_citations(answer)}\n\nVerify."

        try:
            raw = self._llm.complete(self._SYSTEM, user)
        except LlmError as exc:
            logger.warning("grounding.judge.failed", extra={"error": str(exc)})
            result = self._fallback.score(answer=answer, cited_texts=cited_texts)
            result.detail["judge_error"] = str(exc)[:200]
            return result

        match = _JSON_OBJECT_RE.search(raw or "")
        if not match:
            logger.warning("grounding.judge.unparseable")
            return self._fallback.score(answer=answer, cited_texts=cited_texts)

        try:
            data = json.loads(match.group(0))
            total = int(data.get("total") or 0)
            supported = int(data.get("supported") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("grounding.judge.bad_json")
            return self._fallback.score(answer=answer, cited_texts=cited_texts)

        if total <= 0:
            return FaithfulnessResult(
                score=1.0, backend=self.backend, detail={"reason": "no_claims_judged"}
            )

        supported = max(0, min(supported, total))
        unsupported = data.get("unsupported")
        return FaithfulnessResult(
            score=supported / total,
            backend=self.backend,
            supported_claims=supported,
            total_claims=total,
            unsupported=[str(u) for u in unsupported][:5]
            if isinstance(unsupported, list)
            else [],
        )
