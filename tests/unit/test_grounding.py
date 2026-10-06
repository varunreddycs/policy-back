"""S1: post-generation groundedness verification."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.core.dtos import (
    AnswerSource,
    AskRequest,
    EvidenceCandidate,
    PolicyScope,
    RefusalCode,
    UserContext,
)
from packages.grounding import (
    LexicalFaithfulnessScorer,
    check_citations,
    extract_handles,
    is_supported_substring,
    strip_citations,
)
from packages.grounding.base import NullFaithfulnessScorer
from packages.grounding.factory import build_scorer
from packages.llm.client import LlmClient, LlmCompletion
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever

SECTION_TEXT = (
    "AC-2 Account Management. The organization reviews accounts for compliance "
    "with account management requirements every 90 days and disables accounts "
    "within 24 hours of a user termination."
)


class _StaticRetriever(IVectorRetriever):
    def __init__(self, items: list[EvidenceCandidate]) -> None:
        self._items = items

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        scope: PolicyScope | None = None,
        user: UserContext | None = None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        return self._items


class _ScriptedLlm(LlmClient):
    def __init__(self, reply: str) -> None:
        super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")
        self._reply = reply

    def complete_detailed(self, system_prompt: str, user_message: str) -> LlmCompletion:
        return LlmCompletion(content=self._reply, finish_reason="stop")


def _candidate(text: str = SECTION_TEXT) -> EvidenceCandidate:
    return EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text=text,
        score=0.9,
        source="hybrid",
        metadata={
            "department_scope": "all",
            "is_current": True,
            "section_path": "AC-2",
            "vector_similarity": 0.8,
        },
    )


def _request() -> AskRequest:
    tid = uuid4()
    return AskRequest(
        tenant_id=tid,
        question="How often must accounts be reviewed?",
        user=UserContext(tenant_id=tid),
    )


def _ask(reply: str, candidates: list[EvidenceCandidate] | None = None):
    cands = candidates if candidates is not None else [_candidate()]
    return AnswerService(
        retriever=_StaticRetriever(cands), llm=_ScriptedLlm(reply)
    ).ask(_request())


# --- handle parsing -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Accounts reviewed every 90 days [E1].", ["E1"]),
        ("Both apply [E1][E3].", ["E1", "E3"]),
        ("Combined [E2, E4].", ["E2", "E4"]),
        ("lowercase [e5].", ["E5"]),
        ("Repeated [E1] and again [E1].", ["E1"]),
        ("No citation here.", []),
        ("Control id is not a handle [AC-2].", []),
    ],
)
def test_extract_handles(text: str, expected: list[str]) -> None:
    assert extract_handles(text) == expected


def test_strip_citations_leaves_prose() -> None:
    assert strip_citations("Reviewed every 90 days [E1].") == "Reviewed every 90 days ."


# --- substring verification --------------------------------------------


def test_verbatim_quote_is_supported() -> None:
    assert is_supported_substring("reviews accounts for compliance", SECTION_TEXT)


def test_near_verbatim_quote_is_supported() -> None:
    """Whitespace and punctuation drift must not fail an honest quote."""
    assert is_supported_substring("reviews  accounts for   compliance!", SECTION_TEXT)


def test_fabricated_quote_is_not_supported() -> None:
    assert not is_supported_substring(
        "accounts are reviewed every thirty minutes by the CISO", SECTION_TEXT
    )


def test_empty_inputs_are_not_supported() -> None:
    assert not is_supported_substring("", SECTION_TEXT)
    assert not is_supported_substring("anything", "")


# --- citation checking --------------------------------------------------


def test_check_citations_maps_valid_and_unknown_handles() -> None:
    check = check_citations("A [E1] and B [E9].", [_candidate(), _candidate()])

    assert check.valid_handles == ["E1"]
    assert check.unknown_handles == ["E9"]
    assert check.hallucinated_handles is True


def test_citation_density_counts_only_substantive_claims() -> None:
    answer = (
        "Accounts must be reviewed for compliance every 90 days [E1]. "
        "Here is a summary."
    )
    check = check_citations(answer, [_candidate()])

    assert check.total_sentences == 1
    assert check.uncited_sentences == []
    assert check.citation_density == 1.0


# --- lexical scorer -----------------------------------------------------


def test_scorer_supports_a_faithful_answer() -> None:
    result = LexicalFaithfulnessScorer().score(
        answer="The organization reviews accounts for compliance every 90 days [E1].",
        cited_texts=[SECTION_TEXT],
    )

    assert result.score == 1.0
    assert result.backend == "lexical"


def test_scorer_catches_a_fabricated_number() -> None:
    """The classic compliance hallucination: a deadline that is not in the source."""
    result = LexicalFaithfulnessScorer().score(
        answer="The organization reviews accounts for compliance every 30 days [E1].",
        cited_texts=[SECTION_TEXT],
    )

    assert result.score < 1.0
    assert result.unsupported


def test_scorer_catches_a_fabricated_control_id() -> None:
    result = LexicalFaithfulnessScorer().score(
        answer="Account reviews for compliance are governed by control SC-7 [E1].",
        cited_texts=[SECTION_TEXT],
    )

    assert result.score < 1.0


def test_scorer_scores_zero_without_cited_evidence() -> None:
    result = LexicalFaithfulnessScorer().score(
        answer="Anything at all.", cited_texts=[]
    )

    assert result.score == 0.0
    assert result.detail["reason"] == "no_cited_evidence"


# --- factory ------------------------------------------------------------


def test_factory_defaults_to_lexical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAITHFULNESS_BACKEND", raising=False)
    monkeypatch.delenv("GROUNDEDNESS_VERIFY", raising=False)
    assert isinstance(build_scorer(), LexicalFaithfulnessScorer)


def test_factory_unknown_backend_degrades_to_lexical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "not-a-backend")
    assert isinstance(build_scorer(), LexicalFaithfulnessScorer)


def test_factory_honours_verification_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDEDNESS_VERIFY", "false")
    assert isinstance(build_scorer(), NullFaithfulnessScorer)


def test_hhem_degrades_when_transformers_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transformers is deliberately not a dependency."""
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "hhem")
    assert isinstance(build_scorer(), LexicalFaithfulnessScorer)


# --- the enforced gate --------------------------------------------------


def test_uncited_answer_is_refused() -> None:
    """The previously-dead citation_enforcer, now enforced."""
    response = _ask("Accounts must be reviewed every 90 days.")

    assert response.refusal_reason == RefusalCode.UNGROUNDED_ANSWER
    assert response.answer_source is AnswerSource.REFUSAL
    assert response.citations == []
    assert response.grounding is not None
    assert response.grounding.verified is False
    assert "no citation" in (response.grounding.failure_reason or "")


def test_invented_handle_is_refused() -> None:
    """Citing evidence that was never supplied is a fabrication."""
    response = _ask("Accounts must be reviewed every 90 days [E7].")

    assert response.refusal_reason == RefusalCode.UNGROUNDED_ANSWER
    assert response.grounding is not None
    assert response.grounding.unknown_handles == ["E7"]


def test_fabricated_quote_is_refused() -> None:
    """A quoted passage must appear in the section it is attributed to."""
    fabricated = (
        'The policy states "accounts are purged every fifteen minutes without '
        'notice" [E1].'
    )
    response = _ask(fabricated)

    assert response.refusal_reason == RefusalCode.UNGROUNDED_ANSWER
    assert response.grounding is not None
    assert response.grounding.unverified_citations >= 1


def test_grounded_answer_passes_verification() -> None:
    response = _ask(
        "The organization reviews accounts for compliance every 90 days [E1]."
    )

    assert response.refusal_reason is None
    assert response.answer_source is AnswerSource.LLM
    assert response.grounding is not None
    assert response.grounding.verified is True
    assert response.grounding.faithfulness_score == 1.0


def test_citations_come_from_the_model_not_retrieval_ranking() -> None:
    """The core S1 fix: citations previously came from ranked_primary[:5].

    Two sections are retrieved and both are shown to the model, but the answer
    cites only one. Only the cited section may be returned as a citation.
    """
    relevant = _candidate()
    other = _candidate(
        "The organization reviews accounts for compliance every 90 days as well."
    )
    shown: list[EvidenceCandidate] = []

    class _RecordingLlm(LlmClient):
        def __init__(self) -> None:
            super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")

        def complete_detailed(
            self, system_prompt: str, user_message: str
        ) -> LlmCompletion:
            # Cite whichever handle the service actually assigned to `relevant`.
            for index, line in enumerate(
                [ln for ln in user_message.splitlines() if ln.startswith("[E")],
                start=1,
            ):
                if (relevant.text or "")[:40] in line:
                    shown.append(relevant)
                    return LlmCompletion(
                        content=(
                            "The organization reviews accounts for compliance "
                            f"every 90 days [E{index}]."
                        ),
                        finish_reason="stop",
                    )
            raise AssertionError("evidence not found in prompt")

    response = AnswerService(
        retriever=_StaticRetriever([relevant, other]), llm=_RecordingLlm()
    ).ask(_request())

    assert response.refusal_reason is None
    assert len(response.citation_items) == 1, "only the cited section may be returned"
    assert response.citation_items[0].section_id == relevant.section_id


def test_report_only_mode_records_but_does_not_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROUNDEDNESS_ENFORCE", "false")

    response = _ask("Accounts must be reviewed every 90 days.")

    assert response.refusal_reason is None, "report-only must not refuse"
    assert response.grounding is not None
    assert response.grounding.verified is False
    assert response.grounding.enforced is False


def test_verification_can_be_disabled_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDEDNESS_VERIFY", "false")

    response = _ask("Accounts must be reviewed every 90 days.")

    assert response.refusal_reason is None
    assert response.grounding is None


def test_excerpt_fallback_is_grounded_by_construction() -> None:
    """The fallback returns source text verbatim, so it needs no verification."""
    unconfigured = LlmClient(endpoint="", api_key="", deployment="")
    response = AnswerService(
        retriever=_StaticRetriever([_candidate()]), llm=unconfigured
    ).ask(_request())

    assert response.refusal_reason is None
    assert response.answer_source is AnswerSource.EXCERPT_FALLBACK
    assert response.citation_items
