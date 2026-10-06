"""API tests for the references endpoints against an in-memory repository set.

The endpoints must go through the repository layer (not a raw SQLAlchemy
session) so they work under DB_BACKEND=cosmos.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.deps import get_db, get_repositories
from apps.api.main import create_app
from packages.db.repositories.factory import RepositorySet
from packages.db.repositories.repo_dtos import PolicyReferenceDTO

TENANT = uuid.uuid4()
SECTION = uuid.uuid4()
OTHER_SECTION = uuid.uuid4()
VERSION = uuid.uuid4()


def _ref(source: uuid.UUID, target: uuid.UUID | None) -> PolicyReferenceDTO:
    return PolicyReferenceDTO(
        id=uuid.uuid4(),
        reference_type="internal_section",
        resolution_status="resolved",
        matched_text="see section 4",
        confidence=1.0,
        extractor_version="v1",
        source_section_id=source,
        source_policy_version_id=VERSION,
        target_section_id=target,
        target_section_title="Target title" if target else None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeReferences:
    def __init__(self) -> None:
        self.outbound = [_ref(SECTION, OTHER_SECTION)]
        self.inbound = [_ref(OTHER_SECTION, SECTION), _ref(OTHER_SECTION, SECTION)]
        self.version_calls: list[tuple[int, int]] = []

    def section_exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        return tenant_id == TENANT and section_id == SECTION

    def policy_version_exists_for_tenant(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID) -> bool:
        return tenant_id == TENANT and policy_version_id == VERSION

    def list_outbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> list[PolicyReferenceDTO]:
        return self.outbound

    def list_inbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> list[PolicyReferenceDTO]:
        return self.inbound

    def list_for_policy_version(
        self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[PolicyReferenceDTO]:
        self.version_calls.append((limit, offset))
        return self.outbound


@pytest.fixture
def fake_refs() -> _FakeReferences:
    return _FakeReferences()


@pytest.fixture
def client(fake_refs: _FakeReferences) -> Iterator[TestClient]:
    app = create_app()
    repos = RepositorySet(
        policies=object(),
        versions=object(),
        sections=object(),
        embeddings=object(),
        audit=object(),
        ingest_batches=object(),
        ingest_items=object(),
        references=fake_refs,
    )
    app.dependency_overrides[get_repositories] = lambda: repos
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_section_references_returns_outbound_and_inbound(client: TestClient) -> None:
    response = client.get(f"/v1/policy-sections/{SECTION}/references", params={"tenant_id": str(TENANT)})

    assert response.status_code == 200
    body = response.json()
    assert len(body["outbound"]) == 1
    assert len(body["inbound"]) == 2
    assert body["outbound"][0]["target_section_title"] == "Target title"


def test_direction_outbound_omits_inbound(client: TestClient) -> None:
    response = client.get(
        f"/v1/policy-sections/{SECTION}/references",
        params={"tenant_id": str(TENANT), "direction": "outbound"},
    )

    assert response.status_code == 200
    assert len(response.json()["outbound"]) == 1
    assert response.json()["inbound"] == []


def test_unknown_section_is_404(client: TestClient) -> None:
    response = client.get(f"/v1/policy-sections/{uuid.uuid4()}/references", params={"tenant_id": str(TENANT)})

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_version_references_passes_limit_and_offset(client: TestClient, fake_refs: _FakeReferences) -> None:
    response = client.get(
        f"/v1/policy-versions/{VERSION}/references",
        params={"tenant_id": str(TENANT), "limit": 7, "offset": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["limit"], body["offset"]) == (7, 3)
    assert len(body["items"]) == 1
    assert fake_refs.version_calls == [(7, 3)]


def test_unknown_version_is_404(client: TestClient) -> None:
    response = client.get(f"/v1/policy-versions/{uuid.uuid4()}/references", params={"tenant_id": str(TENANT)})

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_router_does_not_depend_on_sql_session(client: TestClient) -> None:
    # Production failure mode: under DB_BACKEND=cosmos get_db yields None, and the
    # router used to call .execute() on it (500). It must use repositories only.
    client.app.dependency_overrides[get_db] = lambda: None  # type: ignore[attr-defined]

    response = client.get(f"/v1/policy-sections/{SECTION}/references", params={"tenant_id": str(TENANT)})

    assert response.status_code == 200
