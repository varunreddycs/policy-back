from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from packages.core.dtos import (
    AnswerSource,
    AskRequest,
    EvidenceCandidate,
    PolicyScope,
    RefusalCode,
    UserContext,
)
from packages.llm.client import REFUSAL_PHRASE, LlmClient, LlmCompletion, LlmError
from packages.rag.answer_service import AnswerService
from packages.retrieval.base import IVectorRetriever


class _RefusingLlm(LlmClient):
    """Stub LLM that always emits the refusal phrase."""

    def __init__(self) -> None:
        super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")

    def complete_detailed(self, system_prompt: str, user_message: str) -> LlmCompletion:
        return LlmCompletion(content=REFUSAL_PHRASE, finish_reason="stop")


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


def _make_request(department: str = "operations") -> AskRequest:
    tenant_id = uuid4()
    return AskRequest(
        tenant_id=tenant_id,
        question="What is the submission timeline?",
        mode="strict",
        user=UserContext(
            tenant_id=tenant_id,
            email="dev@local",
            role="user",
            department=department,
        ),
    )


def test_answer_service_returns_rich_citation_and_decision_fields() -> None:
    tenant_policy = uuid4()
    dept_version = uuid4()
    dept_section = uuid4()
    org_version = uuid4()
    org_section = uuid4()

    candidates = [
        EvidenceCandidate(
            policy_id=tenant_policy,
            policy_version_id=dept_version,
            section_id=dept_section,
            text="Department guidance requires submission within 30 days.",
            score=0.91,
            source="hybrid",
            metadata={
                "department_scope": "operations",
                "user_department": "operations",
                "authority_level": 80,
                "title": "Submission Rules",
                "section_path": "Process/Deadlines",
                "policy_name": "Department Guidance",
                "public_url": "https://example.org/department/guidance",
                "effective_date": "2026-03-01",
                "is_current": True,
            },
        ),
        EvidenceCandidate(
            policy_id=tenant_policy,
            policy_version_id=org_version,
            section_id=org_section,
            text="Organization guidance allows submission within 60 days.",
            score=0.88,
            source="hybrid",
            metadata={
                "department_scope": "all",
                "user_department": "operations",
                "authority_level": 60,
                "title": "General Guidance",
                "section_path": "General/Process",
                "policy_name": "Organization Guidance",
                "public_url": "https://example.org/org/guidance",
                "effective_date": "2026-01-01",
                "is_current": True,
            },
        ),
    ]

    service = AnswerService(retriever=_StaticRetriever(candidates))
    response = service.ask(_make_request())

    assert response.refusal_reason is None
    assert response.decision is not None
    assert response.decision.selected_bucket == "department_specific"
    assert response.decision.primary_candidates == 1
    assert response.decision.secondary_candidates == 1

    assert response.citation_items
    assert response.citation_items[0].policy_name == "Department Guidance"
    assert (
        response.citation_items[0].public_url
        == "https://example.org/department/guidance"
    )
    assert response.secondary_evidence
    assert response.secondary_evidence[0].policy_name == "Organization Guidance"
    assert response.created_at <= datetime.now(timezone.utc)


def test_answer_service_insufficient_evidence_keeps_additive_fields_stable() -> None:
    service = AnswerService(retriever=_StaticRetriever([]))
    response = service.ask(_make_request())

    assert response.refusal_reason == RefusalCode.NO_AUTHORITATIVE_CONTROL
    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.NO_AUTHORITATIVE_CONTROL
    assert response.refusal.explanation
    assert response.refusal.candidates_considered == 0
    assert response.citations == []
    assert response.citation_items == []
    assert response.secondary_evidence == []


def test_answer_service_cross_dept_candidates_surface_in_secondary_evidence() -> None:
    """Phase 2.7: JFS-scoped candidates for an OPS user must appear in secondary evidence."""
    tid = uuid4()
    pid = uuid4()

    ops = EvidenceCandidate(
        policy_id=pid,
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Operations policy: submit within 30 days.",
        score=0.91,
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "authority_level": 80,
            "policy_name": "Ops Handbook",
            "is_current": True,
        },
    )
    org = EvidenceCandidate(
        policy_id=pid,
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Org-wide policy: submit within 60 days.",
        score=0.87,
        source="hybrid",
        metadata={
            "department_scope": "all",
            "user_department": "operations",
            "authority_level": 60,
            "policy_name": "Enterprise Guidance",
            "is_current": True,
        },
    )
    jfs = EvidenceCandidate(
        policy_id=pid,
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="JFS policy: submit within 45 days.",
        score=0.88,
        source="hybrid",
        metadata={
            "department_scope": "jfs",
            "user_department": "operations",
            "authority_level": 70,
            "policy_name": "JFS Handbook",
            "is_current": True,
        },
    )

    request = AskRequest(
        tenant_id=tid,
        question="What is the submission deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )

    service = AnswerService(retriever=_StaticRetriever([ops, org, jfs]))
    response = service.ask(request)

    assert response.decision is not None
    assert response.decision.selected_bucket == "department_specific"
    # JFS + org-wide both go to secondary; at least one should clear the 80% threshold
    secondary_depts = {s.department_scope for s in response.secondary_evidence}
    assert secondary_depts, (
        "secondary_evidence should not be empty for cross-dept conflicts"
    )
    # Primary winner must be operations-scoped
    assert (
        "30 days" in response.answer
        or response.citation_items[0].policy_name == "Ops Handbook"
    )


def test_answer_service_populates_retrieval_log() -> None:
    """Phase 2.7: retrieval_log must be returned alongside the answer for observability."""
    tid = uuid4()
    pid = uuid4()
    candidate = EvidenceCandidate(
        policy_id=pid,
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Operations policy: submit within 30 days.",
        score=0.91,
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "authority_level": 80,
            "policy_name": "Ops Handbook",
            "is_current": True,
            "hybrid_vector_candidates": 12,
            "hybrid_fts_candidates": 8,
            "hybrid_merged_candidates": 17,
            "hybrid_filtered_candidates": 9,
        },
    )
    request = AskRequest(
        tenant_id=tid,
        question="What is the submission deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.retrieval_log is not None
    log = response.retrieval_log
    assert log["fts_candidates"] == 8
    assert log["vector_candidates"] == 12
    assert log["merged"] == 17
    assert log["filtered"] == 9
    assert log["selected_bucket"] == "department_specific"
    assert log["primary_score"] == 0.91


def test_answer_service_refuses_when_primary_score_below_threshold() -> None:
    """Phase 2.7: even with candidates, refuse when primary_score < 0.5."""
    tid = uuid4()
    pid = uuid4()
    weak = EvidenceCandidate(
        policy_id=pid,
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Marginal evidence",
        score=0.42,
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "is_current": True,
        },
    )
    request = AskRequest(
        tenant_id=tid,
        question="What is the submission deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )
    response = AnswerService(retriever=_StaticRetriever([weak])).ask(request)

    assert response.refusal_reason == RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD
    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD
    assert response.refusal.best_score == 0.42
    assert response.refusal.threshold == 0.5
    assert response.refusal.selected_bucket == "department_specific"
    assert response.confidence == 0.0
    assert response.citation_items == []
    assert response.retrieval_log is not None


def test_answer_service_refuses_with_scope_ambiguous_on_cross_dept_fallback() -> None:
    """Q1: a weak match that only came from the cross-department bucket is a scope finding."""
    tid = uuid4()
    candidate = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Some other department's rule.",
        score=0.31,
        source="hybrid",
        metadata={
            "department_scope": "jfs",
            "user_department": "operations",
            "is_current": True,
        },
    )
    request = AskRequest(
        tenant_id=tid,
        question="What is the deadline?",
        user=UserContext(tenant_id=tid, department="operations"),
    )

    response = AnswerService(retriever=_StaticRetriever([candidate])).ask(request)

    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.DEPARTMENT_SCOPE_AMBIGUOUS
    assert response.refusal.selected_bucket == "other"
    assert response.refusal.candidates_considered == 1
    assert "cross-department" in response.refusal.explanation


def test_answer_service_refusal_codes_are_distinct_across_gates() -> None:
    """Q1: the three gates must not collapse to one reason."""
    weak = EvidenceCandidate(
        policy_id=uuid4(),
        policy_version_id=uuid4(),
        section_id=uuid4(),
        text="Marginal",
        score=0.1,
        source="hybrid",
        metadata={"department_scope": "operations", "user_department": "operations"},
    )

    empty = AnswerService(retriever=_StaticRetriever([])).ask(_make_request())
    below = AnswerService(retriever=_StaticRetriever([weak])).ask(_make_request())

    assert empty.refusal_reason != below.refusal_reason
    assert {empty.refusal_reason, below.refusal_reason} == {
        RefusalCode.NO_AUTHORITATIVE_CONTROL,
        RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD,
    }


def _strong(policy_id, version_id, text: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        policy_id=policy_id,
        policy_version_id=version_id,
        section_id=uuid4(),
        text=text,
        score=0.92,
        source="hybrid",
        metadata={
            "department_scope": "operations",
            "user_department": "operations",
            "is_current": True,
        },
    )


def test_answer_service_llm_refusal_reports_conflicting_versions() -> None:
    """Q1: two versions of the SAME policy behind an LLM refusal is a version conflict."""
    policy_id = uuid4()
    candidates = [
        _strong(policy_id, uuid4(), "v1: submit within 30 days."),
        _strong(policy_id, uuid4(), "v2: submit within 60 days."),
    ]

    service = AnswerService(retriever=_StaticRetriever(candidates), llm=_RefusingLlm())
    response = service.ask(_make_request())

    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.CONFLICTING_VERSIONS
    assert response.refusal_reason == RefusalCode.CONFLICTING_VERSIONS
    assert response.citation_items == []


def test_answer_service_llm_refusal_on_distinct_policies_is_no_control() -> None:
    """Q1: distinct policies behind an LLM refusal means no control covers the question."""
    candidates = [
        _strong(uuid4(), uuid4(), "Unrelated rule A."),
        _strong(uuid4(), uuid4(), "Unrelated rule B."),
    ]

    service = AnswerService(retriever=_StaticRetriever(candidates), llm=_RefusingLlm())
    response = service.ask(_make_request())

    assert response.refusal is not None
    assert response.refusal.code is RefusalCode.NO_AUTHORITATIVE_CONTROL


class _FailingLlm(LlmClient):
    """Stub LLM that always fails, to exercise the excerpt fallback."""

    def __init__(self, message: str = "upstream throttled") -> None:
        super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")
        self._message = message

    def complete_detailed(self, system_prompt: str, user_message: str) -> LlmCompletion:
        raise LlmError(self._message)


def test_answer_marks_llm_source_when_generation_succeeds() -> None:
    """Q2: a genuine generated answer is flagged as such."""
    candidate = _strong(uuid4(), uuid4(), "Submit within 30 days.")

    class _Ok(LlmClient):
        def __init__(self) -> None:
            super().__init__(endpoint="https://stub", api_key="stub", deployment="stub")

        def complete_detailed(
            self, system_prompt: str, user_message: str
        ) -> LlmCompletion:
            return LlmCompletion(
                content="Submit within 30 days of the event [E1].", finish_reason="stop"
            )

    response = AnswerService(retriever=_StaticRetriever([candidate]), llm=_Ok()).ask(
        _make_request()
    )

    assert response.answer_source is AnswerSource.LLM
    assert response.is_fallback is False
    assert response.llm_error is None


def test_excerpt_fallback_is_flagged_with_reason() -> None:
    """Q2: a degraded answer must never look like a generated one."""
    candidate = _strong(uuid4(), uuid4(), "Submit within 30 days.")

    response = AnswerService(
        retriever=_StaticRetriever([candidate]), llm=_FailingLlm("HTTP 429")
    ).ask(_make_request())

    assert response.answer_source is AnswerSource.EXCERPT_FALLBACK
    assert response.is_fallback is True
    assert response.llm_error is not None
    assert "429" in response.llm_error
    # the excerpt itself still answers, with a citation
    assert "30 days" in response.answer


def test_unconfigured_llm_reports_not_configured() -> None:
    candidate = _strong(uuid4(), uuid4(), "Submit within 30 days.")
    unconfigured = LlmClient(endpoint="", api_key="", deployment="")

    response = AnswerService(
        retriever=_StaticRetriever([candidate]), llm=unconfigured
    ).ask(_make_request())

    assert response.answer_source is AnswerSource.EXCERPT_FALLBACK
    assert response.llm_error == "llm_not_configured"
