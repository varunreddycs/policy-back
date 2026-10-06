"""Q3: the eval harness scoring and gate logic must itself be correct.

These run with no stack and no LLM — they test the scorer, not the RAG system.
"""

from __future__ import annotations

from typing import Any

from packages.eval.baseline import build_report, compare, newly_refused
from packages.eval.metrics import aggregate, score_response
from packages.eval.questions import load_questions


def _answered_response(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "answer": "Submit within 30 days [policy_version_id=v1 section_id=s1].",
        "citations": ["[policy_version_id=v1 section_id=s1]"],
        "citation_items": [{"policy_version_id": "v1"}],
        "evidence": [{"policy_version_id": "v1", "section_id": "s1"}],
        "secondary_evidence": [],
        "confidence": 0.82,
        "refusal_reason": None,
        "is_fallback": False,
        "answer_source": "llm",
        "decision": {"selected_bucket": "department_specific"},
        "retrieval_log": {
            "fts_candidates": 8,
            "vector_candidates": 12,
            "merged": 17,
            "primary_score": 0.82,
        },
    }
    payload.update(overrides)
    return payload


def _score(response: dict[str, Any], status: int = 200, qid: str = "ohio/general/q"):
    return score_response(
        question_id=qid,
        suite="ohio",
        category="general",
        variant="strict",
        question="What is the deadline?",
        status=status,
        response=response,
    )


# --- question loading ---------------------------------------------------


def test_load_questions_finds_the_committed_set() -> None:
    questions = load_questions()
    assert len(questions) >= 20
    assert all(q.question for q in questions)


def test_load_questions_excludes_templates() -> None:
    questions = load_questions()
    assert not any("_templates" in q.question_id for q in questions)
    assert not any("REPLACE_WITH_YOUR_QUESTION" in q.question for q in questions)


def test_question_ids_are_unique_and_stable() -> None:
    ids = [q.question_id for q in load_questions()]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


# --- scoring ------------------------------------------------------------


def test_scores_an_answered_response() -> None:
    result = _score(_answered_response())

    assert result.answered is True
    assert result.refused is False
    assert result.citation_count == 1
    assert result.evidence_count == 1
    assert result.confidence == 0.82
    assert result.selected_bucket == "department_specific"
    assert result.fts_candidates == 8
    assert result.vector_candidates == 12
    assert result.answer_cites_evidence is True


def test_scores_a_refusal() -> None:
    result = _score(
        _answered_response(
            answer="Insufficient evidence in available policy sections.",
            refusal_reason="below_groundedness_threshold",
            citations=[],
            citation_items=[],
        )
    )

    assert result.refused is True
    assert result.answered is False
    assert result.refusal_code == "below_groundedness_threshold"


def test_scores_a_fallback_answer() -> None:
    result = _score(
        _answered_response(is_fallback=True, answer_source="excerpt_fallback")
    )

    assert result.is_fallback is True
    assert result.answer_source == "excerpt_fallback"


def test_non_200_is_recorded_as_an_error_not_an_answer() -> None:
    result = _score({}, status=500)

    assert result.status == 500
    assert result.answered is False
    assert result.citation_count == 0


def test_answer_without_a_citation_handle_is_not_grounded() -> None:
    """A prompt edit that drops the citation format must be visible."""
    result = _score(_answered_response(answer="Submit within 30 days."))

    assert result.answered is True
    assert result.answer_cites_evidence is False


def test_citation_handle_for_unretrieved_version_is_not_grounded() -> None:
    result = _score(
        _answered_response(
            answer="See [policy_version_id=OTHER section_id=s9].",
            evidence=[{"policy_version_id": "v1"}],
        )
    )

    assert result.answer_cites_evidence is False


def test_control_ids_are_extracted() -> None:
    result = _score(_answered_response(answer="Per AC-2 and IA-5(1), review accounts."))

    assert result.control_ids_in_answer == ["AC-2", "IA-5(1)"]


# --- aggregation --------------------------------------------------------


def test_aggregate_computes_rates() -> None:
    results = [
        _score(_answered_response(), qid="a"),
        _score(_answered_response(), qid="b"),
        _score(
            _answered_response(refusal_reason="no_authoritative_control", citations=[]),
            qid="c",
        ),
        _score({}, status=500, qid="d"),
    ]

    metrics = aggregate(results)

    assert metrics.total == 4
    assert metrics.answered == 2
    assert metrics.refused == 1
    assert metrics.errors == 1
    assert metrics.answer_rate == 0.5
    assert metrics.refusal_rate == 0.25
    assert metrics.citation_coverage == 1.0
    assert metrics.refusal_codes == {"no_authoritative_control": 1}
    assert metrics.buckets["department_specific"] == 3


def test_aggregate_handles_empty_input() -> None:
    metrics = aggregate([])
    assert metrics.total == 0
    assert metrics.answer_rate == 0.0


# --- baseline gate ------------------------------------------------------


def _baseline_from(results: list[Any], backend: str = "hybrid") -> dict[str, Any]:
    return build_report(aggregate(results), results, backend=backend)


def test_identical_run_reports_no_regression() -> None:
    results = [_score(_answered_response(), qid=f"q{i}") for i in range(4)]
    baseline = _baseline_from(results)

    assert compare(aggregate(results), baseline) == []


def test_drop_in_answer_rate_is_a_regression() -> None:
    good = [_score(_answered_response(), qid=f"q{i}") for i in range(4)]
    baseline = _baseline_from(good)

    degraded = [
        _score(
            _answered_response(refusal_reason="no_authoritative_control"), qid=f"q{i}"
        )
        for i in range(4)
    ]
    regressions = compare(aggregate(degraded), baseline)

    names = {r.metric for r in regressions}
    assert "answer_rate" in names
    assert "refusal_rate" in names


def test_small_movement_within_tolerance_is_not_a_regression() -> None:
    good = [_score(_answered_response(), qid=f"q{i}") for i in range(100)]
    baseline = _baseline_from(good)

    # one of 100 flips: 0.01 movement, inside the 0.05 band
    slightly_worse = good[:99] + [
        _score(_answered_response(refusal_reason="no_authoritative_control"), qid="q99")
    ]

    assert compare(aggregate(slightly_worse), baseline) == []


def test_losing_the_citation_format_is_a_regression() -> None:
    """The exact failure mode an edited strict-citation prompt would cause."""
    good = [_score(_answered_response(), qid=f"q{i}") for i in range(4)]
    baseline = _baseline_from(good)

    uncited = [
        _score(_answered_response(answer="Submit within 30 days."), qid=f"q{i}")
        for i in range(4)
    ]
    regressions = compare(aggregate(uncited), baseline)

    assert "grounded_citation_rate" in {r.metric for r in regressions}


def test_newly_refused_attributes_the_change_to_questions() -> None:
    good = [_score(_answered_response(), qid=f"q{i}") for i in range(3)]
    baseline = _baseline_from(good)

    now = [
        _score(_answered_response(), qid="q0"),
        _score(_answered_response(refusal_reason="no_authoritative_control"), qid="q1"),
        _score(_answered_response(refusal_reason="conflicting_versions"), qid="q2"),
    ]

    assert newly_refused(now, baseline) == ["q1", "q2"]


def test_report_records_the_backend_it_ran_against() -> None:
    results = [_score(_answered_response(), qid="q0")]
    report = _baseline_from(results, backend="pgvector")

    assert report["retriever_backend"] == "pgvector"
    assert "q0" in report["questions"]
    assert report["metrics"]["total"] == 1


def test_s1_evidence_handle_counts_as_grounded() -> None:
    """S1 answers cite [En] handles; n within the returned evidence is grounded."""
    result = _score(_answered_response(answer="Reviews happen every 90 days [E1]."))

    assert result.answer_cites_evidence is True


def test_out_of_range_evidence_handle_is_not_grounded() -> None:
    result = _score(_answered_response(answer="Reviews happen every 90 days [E7]."))

    assert result.answer_cites_evidence is False
