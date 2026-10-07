"""Q7: control-ID retrieval parity across backends."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.core.dtos import EvidenceCandidate, PolicyScope, UserContext
from packages.retrieval.base import IVectorRetriever
from packages.retrieval.control_ids import (
    boost_exact_control_matches,
    extract_control_ids,
    normalize_control_ids,
)
from packages.retrieval.hybrid_provider import HybridRetriever


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


def _cand(
    section_path: str, score: float, *, text: str = "control text"
) -> EvidenceCandidate:
    return EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text=text,
        score=score,
        source="pgvector",
        metadata={
            "section_path": section_path,
            "department_scope": "all",
            "is_current": True,
        },
    )


# --- extraction ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What does AC-2 require?", {"AC-2"}),
        ("what does ac-2 require", {"AC-2"}),
        ("AC-02 and ac-2 are the same", {"AC-2"}),
        ("See IA-5(1) for details", {"IA-5(1)"}),
        ("SC-7(3) and AC-2 both apply", {"SC-7(3)", "AC-2"}),
        ("no identifiers here", set()),
        ("", set()),
    ],
)
def test_extract_control_ids(text: str, expected: set[str]) -> None:
    assert extract_control_ids(text) == expected


def test_enhancement_suffix_is_not_truncated() -> None:
    """Regression: a trailing \\b refused to match ')' and cut IA-5(1) to IA-5."""
    assert extract_control_ids("IA-5(1)") == {"IA-5(1)"}
    assert "IA-5" not in extract_control_ids("IA-5(1)")


# --- normalization ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("what does ac-02 require", "what does AC-2 require"),
        ("AC-2 already canonical", "AC-2 already canonical"),
        ("check ia-5(1) please", "check IA-5(1) please"),
        ("nothing to change", "nothing to change"),
        ("", ""),
    ],
)
def test_normalize_control_ids(raw: str, expected: str) -> None:
    assert normalize_control_ids(raw) == expected


# --- boosting -----------------------------------------------------------


def test_named_control_is_surfaced_above_stronger_neighbours() -> None:
    """The whole point: an exact-identifier query must rank its control first."""
    candidates = [
        _cand("AC-3", 0.88),
        _cand("AC-6", 0.85),
        _cand("AC-2", 0.55),  # the one actually asked for
    ]

    boosted = boost_exact_control_matches("What does AC-2 require?", candidates)

    assert boosted[0].metadata["section_path"] == "AC-2"
    assert boosted[0].metadata["pre_boost_score"] == 0.55
    assert boosted[0].metadata["control_id_boost"] == 0.4


def test_boost_matches_case_and_zero_padding_insensitively() -> None:
    candidates = [_cand("AC-9", 0.9), _cand("AC-2", 0.5)]

    boosted = boost_exact_control_matches("tell me about ac-02", candidates)

    assert boosted[0].metadata["section_path"] == "AC-2"


def test_boost_matches_enhancements() -> None:
    candidates = [_cand("IA-5", 0.9), _cand("IA-5(1)", 0.5)]

    boosted = boost_exact_control_matches("what is IA-5(1)", candidates)

    assert boosted[0].metadata["section_path"] == "IA-5(1)"


def test_query_without_a_control_id_is_untouched() -> None:
    candidates = [_cand("AC-3", 0.88), _cand("AC-2", 0.55)]

    result = boost_exact_control_matches("what is the password policy", candidates)

    assert result is candidates
    assert [c.score for c in result] == [0.88, 0.55]


def test_boost_is_capped_and_never_exceeds_the_ceiling() -> None:
    candidates = [_cand("AC-2", 0.95), _cand("AC-3", 0.9)]

    boosted = boost_exact_control_matches("AC-2", candidates)

    assert boosted[0].score == pytest.approx(0.99)


def test_unmatched_control_id_leaves_ordering_alone() -> None:
    """Naming a control that was not retrieved must not reshuffle results."""
    candidates = [_cand("AC-3", 0.88), _cand("AC-6", 0.55)]

    result = boost_exact_control_matches("what about AC-99", candidates)

    assert [c.metadata["section_path"] for c in result] == ["AC-3", "AC-6"]


def test_boost_reads_title_and_control_id_metadata_too() -> None:
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="text",
        score=0.4,
        source="pgvector",
        metadata={"title": "AC-2 Account Management", "department_scope": "all"},
    )
    other = _cand("AC-9", 0.9)

    boosted = boost_exact_control_matches("AC-2", [other, candidate])

    assert boosted[0].metadata.get("title") == "AC-2 Account Management"


def test_empty_candidates_are_handled() -> None:
    assert boost_exact_control_matches("AC-2", []) == []


# --- postgres parity ----------------------------------------------------


def test_hybrid_applies_the_boost_so_postgres_matches_cosmos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parity gap: this boost previously existed only on the Cosmos path."""
    monkeypatch.setenv("HYBRID_VECTOR_MIN_SIMILARITY", "0.0")
    monkeypatch.setenv("HYBRID_FTS_MIN_SCORE", "0.0")

    near_miss = _cand("AC-3", 0.95)
    asked_for = _cand("AC-2", 0.60)

    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever([near_miss, asked_for]),
        fts_retriever=_StaticRetriever([]),
    )

    results = retriever.retrieve(
        tenant_id=uuid4(), query="What does AC-2 require?", top_k=10
    )

    assert results[0].metadata["section_path"] == "AC-2"
    assert "control_id_boost" in results[0].metadata


def test_hybrid_ordinary_query_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYBRID_VECTOR_MIN_SIMILARITY", "0.0")
    monkeypatch.setenv("HYBRID_FTS_MIN_SCORE", "0.0")

    retriever = HybridRetriever(
        vector_retriever=_StaticRetriever([_cand("AC-3", 0.95), _cand("AC-2", 0.60)]),
        fts_retriever=_StaticRetriever([]),
    )

    results = retriever.retrieve(
        tenant_id=uuid4(), query="what is the password policy", top_k=10
    )

    assert all("control_id_boost" not in (c.metadata or {}) for c in results)


# --- FTS tokenization ---------------------------------------------------


def _fts_tokens(query: str) -> list[str]:
    """Mirror of the token build in PgsqlFtsRetriever.retrieve."""
    import re

    ids = extract_control_ids(query)
    control_tokens = sorted({f"'{cid.lower()}'" for cid in ids})
    control_words = {
        part.lower() for cid in ids for part in re.findall(r"[A-Za-z0-9]+", cid)
    }
    words = [
        t.lower()
        for t in re.findall(r"[A-Za-z0-9]+", query)
        if len(t) >= 3 and t.lower() not in control_words
    ]
    return (control_tokens + words)[:8]


def test_fts_keeps_short_control_codes() -> None:
    """Regression: the >= 3 filter dropped 'ac' and '2', losing AC-2 entirely."""
    tokens = _fts_tokens("What does AC-2 require?")

    assert "'ac-2'" in tokens


def test_fts_control_tokens_are_always_quoted() -> None:
    """An unquoted '(' is a tsquery syntax error; quoting makes it a phrase term.

    Verified against PostgreSQL 16: to_tsquery accepts '''ia-5(1)''' and
    rejects a bare ia-5(1). See test_fts_tsquery_syntax_is_valid in
    tests/integration/test_fts_tsquery.py for the live check.
    """
    for query in [
        "IA-5(1) authenticator management",
        "SC-7(3) boundary protection",
        "ac-02 and sc-7(3)",
    ]:
        for token in _fts_tokens(query):
            if "(" in token or "-" in token:
                assert token.startswith("'") and token.endswith("'"), token


def test_fts_keeps_the_full_enhancement_identifier() -> None:
    """IA-5(1) must not be truncated to IA-5 in the FTS term."""
    assert "'ia-5(1)'" in _fts_tokens("what does IA-5(1) require")


def test_fts_does_not_duplicate_control_words_as_plain_tokens() -> None:
    tokens = _fts_tokens("AC-2 account management")

    assert tokens.count("'ac-2'") == 1
    assert "account" in tokens


# --- CSF subcategory ids are not 800-53 controls --------------------------


@pytest.mark.parametrize(
    "csf_id",
    ["GV.SC-01", "ID.RA-01", "PR.AT-02", "DE.CM-09", "RS.MA-01", "GV.OC-05"],
)
def test_csf_ids_are_not_control_ids(csf_id: str) -> None:
    """Regression: \b let 'SC-01' inside 'GV.SC-01' match as 800-53 SC-1."""
    from packages.core.control_ids import primary_control_id

    assert primary_control_id(csf_id) is None
    assert extract_control_ids(f"see {csf_id} for details") == set()
    assert normalize_control_ids(csf_id) == csf_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AC-2(3)", "AC-2(3)"),
        ("see AC-2.", "AC-2"),
        ("(AC-2)", "AC-2"),
        ("controls: AC-2, AC-3", "AC-2"),
    ],
)
def test_real_control_ids_still_match_after_csf_fix(text: str, expected: str) -> None:
    from packages.core.control_ids import primary_control_id

    assert primary_control_id(text) == expected
