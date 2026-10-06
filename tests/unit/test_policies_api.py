"""Policy version listing with catalog-seeded versions.

The NIST 800-53 seed creates versions from the OSCAL catalog, so they have no
uploaded source file (empty blob_container/blob_name). The list endpoint built
a blob URL for every version unconditionally, and one such version 500'd the
whole response in production.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.deps import get_blob_service, get_policy_query_service
from apps.api.main import create_app
from packages.db.repositories.repo_dtos import PolicyVersionDTO

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
POLICY = uuid.uuid4()


def _version(number: int, *, container: str, name: str) -> PolicyVersionDTO:
    return PolicyVersionDTO(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        policy_id=POLICY,
        version_number=number,
        content_sha256=f"sha-{number}",
        metadata_sha256=f"meta-{number}",
        blob_container=container,
        blob_name=name,
        parse_status="ready",
        # Real versions always carry these; the response schema requires them.
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        parse_status_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeQueryService:
    def __init__(self, versions: list[PolicyVersionDTO]) -> None:
        self._versions = versions

    def list_policy_versions(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> list[PolicyVersionDTO]:
        return self._versions


class _StrictBlob:
    """Raises on an empty container name, exactly as the real BlobService does."""

    def get_blob_uri(self, container: str, name: str) -> str:
        if not container:
            raise ValueError("container_name must be non-empty")
        return f"https://blob/{container}/{name}"


@pytest.fixture
def client_for() -> Iterator[object]:
    app = create_app()

    def _build(versions: list[PolicyVersionDTO]) -> TestClient:
        app.dependency_overrides[get_policy_query_service] = lambda: _FakeQueryService(versions)
        app.dependency_overrides[get_blob_service] = lambda: _StrictBlob()
        return TestClient(app)

    yield _build
    app.dependency_overrides.clear()


def test_catalog_seeded_version_without_blob_does_not_500(client_for) -> None:  # type: ignore[no-untyped-def]
    client = client_for([_version(1, container="", name="")])

    resp = client.get(f"/v1/policies/{POLICY}/versions", params={"tenant_id": str(TENANT)})

    assert resp.status_code == 200
    assert resp.json()[0]["raw_blob_uri"] is None


def test_mixed_versions_keep_blob_uri_for_uploaded_ones(client_for) -> None:  # type: ignore[no-untyped-def]
    client = client_for(
        [
            _version(1, container="", name=""),
            _version(2, container="policy-raw", name="doc-2.pdf"),
        ]
    )

    resp = client.get(f"/v1/policies/{POLICY}/versions", params={"tenant_id": str(TENANT)})

    assert resp.status_code == 200
    uris = [v["raw_blob_uri"] for v in resp.json()]
    assert uris == [None, "https://blob/policy-raw/doc-2.pdf"]
