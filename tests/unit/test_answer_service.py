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
