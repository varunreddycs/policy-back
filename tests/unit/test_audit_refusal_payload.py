"""Q1: refusals must be filterable at the top level of the audit payload."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from packages.core.dtos import AnswerResponse, AskRequest, RefusalCode, RefusalInfo
from packages.db.repositories.base import IAuditRepository
from packages.db.repositories.repo_dtos import AuditLogDTO
from packages.governance.audit_service import AuditService


class _CapturingAuditRepo(IAuditRepository):
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def write(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        correlation_id: str | None,
        payload: dict[str, Any],
    ) -> uuid.UUID:
        self.payloads.append(payload)
        return uuid.uuid4()

    def get_by_id(self, *, audit_id: uuid.UUID) -> AuditLogDTO | None:
        return None

    def list_for_tenant(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[AuditLogDTO]:
        return []


def _request() -> AskRequest:
    return AskRequest(tenant_id=uuid.uuid4(), question="What is the deadline?")


def test_refusal_code_is_promoted_to_top_level_audit_payload() -> None:
    repo = _CapturingAuditRepo()
    response = AnswerResponse(
        answer="Insufficient evidence in available policy sections.",
        refusal_reason=str(RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD),
        refusal=RefusalInfo(
            code=RefusalCode.BELOW_GROUNDEDNESS_THRESHOLD,
            explanation="Best matching section scored 0.420.",
            selected_bucket="department_specific",
            candidates_considered=3,
            best_score=0.42,
            threshold=0.5,
        ),
        created_at=datetime.now(timezone.utc),
    )

    AuditService(audit_repo=repo).write_ask(request=_request(), response=response)

    payload = repo.payloads[0]
    assert payload["refusal_code"] == "below_groundedness_threshold"
    assert payload["refusal"]["best_score"] == 0.42
    assert payload["refusal"]["threshold"] == 0.5


def test_answered_response_records_no_refusal_code() -> None:
    repo = _CapturingAuditRepo()
    response = AnswerResponse(
        answer="Submit within 30 days.",
        confidence=0.91,
        created_at=datetime.now(timezone.utc),
    )

    AuditService(audit_repo=repo).write_ask(request=_request(), response=response)

    assert "refusal_code" not in repo.payloads[0]
