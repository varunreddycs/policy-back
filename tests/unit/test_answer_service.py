from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from packages.core.dtos import AskRequest, EvidenceCandidate, UserContext
from packages.rag.answer_service import AnswerService


class _StaticRetriever:
    def __init__(self, items):
        self._items = items

    def retrieve(self, **kwargs):
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
    assert response.citation_items[0].public_url == "https://example.org/department/guidance"
    assert response.secondary_evidence
    assert response.secondary_evidence[0].policy_name == "Organization Guidance"
    assert response.created_at <= datetime.now(timezone.utc)


def test_answer_service_insufficient_evidence_keeps_additive_fields_stable() -> None:
    service = AnswerService(retriever=_StaticRetriever([]))
    response = service.ask(_make_request())

    assert response.refusal_reason == "insufficient_evidence"
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
    assert secondary_depts, "secondary_evidence should not be empty for cross-dept conflicts"
    # Primary winner must be operations-scoped
    assert "30 days" in response.answer or response.citation_items[0].policy_name == "Ops Handbook"


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

    assert response.refusal_reason == "insufficient_evidence"
    assert response.confidence == 0.0
    assert response.citation_items == []
    assert response.retrieval_log is not None
