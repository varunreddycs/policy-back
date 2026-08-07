"""Regression tests for the cross-tenant audit IDOR (issue #2, [F1]).

An audit row created under tenant A must never be readable or replayable by a
caller asserting tenant B. A wrong-tenant request must be indistinguishable from
a genuinely-missing row: both return HTTP 404 (no existence oracle).

These tests drive the real repository filter (`PgAuditRepository.get_by_id` via a
fake in-memory session), the service layer (`AuditService.get` / `.replay`) and
the router functions (`get_audit_log` / `replay_audit`) directly — matching the
repo's session-free / TestClient-free unit-test style.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from fastapi import HTTPException, status

from apps.api.routers.audit import get_audit_log, replay_audit
from packages.db.repositories.base import IAuditRepository
from packages.db.repositories.repo_dtos import AuditLogDTO
from packages.governance.audit_service import AuditNotFound, AuditService


class _FakeAuditRepo(IAuditRepository):
    """In-memory IAuditRepository stand-in that enforces the tenant filter."""

    def __init__(self, rows: list[AuditLogDTO]) -> None:
        self._rows = rows

    def get_by_id(
        self, *, tenant_id: uuid.UUID, audit_id: uuid.UUID
    ) -> AuditLogDTO | None:
        for row in self._rows:
            if row.id == audit_id and row.tenant_id == tenant_id:
                return row
        return None

    def write(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        correlation_id: str | None,
        payload: dict[str, Any],
    ) -> uuid.UUID:  # pragma: no cover - unused by these tests
        raise NotImplementedError

    def list_for_tenant(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[AuditLogDTO]:  # pragma: no cover - unused by these tests
        raise NotImplementedError


def _make_row(*, audit_id: uuid.UUID, tenant_id: uuid.UUID) -> AuditLogDTO:
    return AuditLogDTO(
        id=audit_id,
        tenant_id=tenant_id,
        event_type="ask",
        payload={
            "request": {
                "query": "secret tenant-A question",
                "tenant_id": str(tenant_id),
            },
            "response": {"answer": "tenant-A answer"},
        },
        correlation_id="corr-a",
        created_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


def test_service_get_returns_row_for_owning_tenant() -> None:
    tenant_a = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )

    record = service.get(tenant_id=tenant_a, audit_id=audit_id)

    assert record["id"] == audit_id
    assert record["tenant_id"] == tenant_a
    assert record["request"]["query"] == "secret tenant-A question"


def test_service_get_raises_not_found_for_other_tenant() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )

    with pytest.raises(AuditNotFound):
        service.get(tenant_id=tenant_b, audit_id=audit_id)


def test_service_get_missing_and_wrong_tenant_are_indistinguishable() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )

    with pytest.raises(AuditNotFound) as wrong_tenant:
        service.get(tenant_id=tenant_b, audit_id=audit_id)
    with pytest.raises(AuditNotFound) as truly_missing:
        service.get(tenant_id=tenant_b, audit_id=uuid.uuid4())

    assert wrong_tenant.value.code == truly_missing.value.code
    assert wrong_tenant.value.message == truly_missing.value.message


# ---------------------------------------------------------------------------
# Router layer — status codes and generic response
# ---------------------------------------------------------------------------


def test_router_get_wrong_tenant_returns_404_not_data() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )

    with pytest.raises(HTTPException) as exc:
        get_audit_log(audit_id=audit_id, tenant_id=tenant_b, audit_service=service)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == {
        "code": "NOT_FOUND",
        "message": "Audit record not found",
    }


def test_router_get_missing_row_returns_identical_404() -> None:
    tenant_b = uuid.uuid4()
    service = AuditService(audit_repo=_FakeAuditRepo([]))

    with pytest.raises(HTTPException) as exc:
        get_audit_log(audit_id=uuid.uuid4(), tenant_id=tenant_b, audit_service=service)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == {
        "code": "NOT_FOUND",
        "message": "Audit record not found",
    }


def test_router_get_owning_tenant_returns_data() -> None:
    tenant_a = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )

    # The router returns a dict at runtime (FastAPI coerces it into the
    # response_model); its declared -> AuditLogResponse annotation predates this fix.
    result = cast(
        dict[str, Any],
        get_audit_log(audit_id=audit_id, tenant_id=tenant_a, audit_service=service),
    )

    assert result["id"] == audit_id
    assert result["tenant_id"] == tenant_a


class _SpyAskService:
    """Records whether ask() was ever invoked (replay must not run cross-tenant)."""

    def __init__(self) -> None:
        self.called = False

    def ask(
        self, request: Any
    ) -> Any:  # pragma: no cover - must never run in these tests
        self.called = True
        raise AssertionError("replay must not re-execute another tenant's query")


def test_router_replay_wrong_tenant_returns_404_and_does_not_execute() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    service = AuditService(
        audit_repo=_FakeAuditRepo([_make_row(audit_id=audit_id, tenant_id=tenant_a)])
    )
    ask_service = _SpyAskService()

    with pytest.raises(HTTPException) as exc:
        replay_audit(
            audit_id=audit_id,
            tenant_id=tenant_b,
            audit_service=service,
            # AskService is a concrete class, not a Protocol; the spy is duck-typed
            ask_service=ask_service,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == {
        "code": "NOT_FOUND",
        "message": "Audit record not found",
    }
    assert ask_service.called is False


# ---------------------------------------------------------------------------
# Repository layer — WHERE clause actually filters by tenant
# ---------------------------------------------------------------------------


class _FakeScalarResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _FilteringSession:
    """Minimal Session mimicking a WHERE id == audit_id AND tenant_id == tenant.

    Inspects the compiled statement's bind params so the test verifies the repo
    supplies BOTH predicates, then returns the stored row only on a full match.
    """

    def __init__(self, *, row: Any, row_id: uuid.UUID, row_tenant: uuid.UUID) -> None:
        self._row = row
        self._row_id = row_id
        self._row_tenant = row_tenant

    def execute(self, stmt: Any) -> _FakeScalarResult:
        params = stmt.compile().params
        wanted = {v for v in params.values() if isinstance(v, uuid.UUID)}
        if self._row_id in wanted and self._row_tenant in wanted:
            return _FakeScalarResult(self._row)
        return _FakeScalarResult(None)


def test_pg_repo_get_by_id_filters_by_tenant() -> None:
    from packages.db.models.governance import AuditLog
    from packages.db.repositories.audit_repo import PgAuditRepository

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    orm_row = AuditLog(
        id=audit_id,
        tenant_id=tenant_a,
        event_type="ask",
        correlation_id="corr-a",
        payload_json={"request": {"query": "q"}},
    )

    session = _FilteringSession(row=orm_row, row_id=audit_id, row_tenant=tenant_a)
    repo = PgAuditRepository(session)  # type: ignore[arg-type]  # fake session, duck-typed

    assert repo.get_by_id(tenant_id=tenant_a, audit_id=audit_id) is not None
    assert repo.get_by_id(tenant_id=tenant_b, audit_id=audit_id) is None
