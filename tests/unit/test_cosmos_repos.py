"""Cosmos repository tests against an in-memory fake container.

The Cosmos repositories had zero direct coverage, which is how a lost-update
bug survived in the code path production actually runs: versions live as a
nested array inside the policy document and were written back with a bare
``upsert_item``, so two concurrent writers each read the same array and the
second overwrote the first.

The fake container below dispatches on the repositories' fixed query-string
shapes rather than executing Cosmos SQL, and models ETag preconditions the way
the real service does (``If-Match`` mismatch -> 412).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from packages.db.repositories.cosmos.concurrency import rmw
from packages.db.repositories.cosmos.cosmos_repos import (
    CosmosIngestItemRepository,
    CosmosPolicyVersionRepository,
)
from packages.db.repositories.errors import RepositoryConflict


class _PreconditionFailed(Exception):
    """Stands in for azure.cosmos.exceptions.CosmosAccessConditionFailedError."""

    status_code = 412


class _FakeContainer:
    """In-memory stand-in for a Cosmos container, keyed by document id."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self._etag_seq = 0

    def _bump_etag(self, doc: dict[str, Any]) -> None:
        self._etag_seq += 1
        doc["_etag"] = f'"etag-{self._etag_seq}"'

    def seed(self, doc: dict[str, Any]) -> dict[str, Any]:
        stored = dict(doc)
        self._bump_etag(stored)
        self.docs[stored["id"]] = stored
        return stored

    def query_items(
        self,
        *,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
        enable_cross_partition_query: bool = False,
    ) -> list[dict[str, Any]]:
        params = {p["name"]: p["value"] for p in (parameters or [])}

        if "c.id = @id" in query:
            doc = self.docs.get(str(params.get("@id")))
            # Deep-copy so a caller mutating its read cannot reach into storage;
            # this is what makes the lost-update race observable.
            return [_deep_copy(doc)] if doc else []

        if "ARRAY_CONTAINS(c.versions" in query:
            target = str(params.get("@vid"))
            return [
                _deep_copy(doc)
                for doc in self.docs.values()
                if any(v.get("id") == target for v in doc.get("versions", []))
            ]

        raise AssertionError(f"Fake container got an unhandled query: {query!r}")

    def upsert_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        existing = self.docs.get(body["id"])
        match_condition = kwargs.get("match_condition")
        etag = kwargs.get("etag")

        if match_condition is not None or etag is not None:
            if existing is not None and etag is not None and existing.get("_etag") != etag:
                raise _PreconditionFailed("etag mismatch")

        stored = _deep_copy(body)
        self._bump_etag(stored)
        self.docs[stored["id"]] = stored
        return stored


def _deep_copy(doc: dict[str, Any] | None) -> dict[str, Any]:
    if doc is None:
        return {}
    copied = dict(doc)
    if "versions" in copied:
        copied["versions"] = [dict(v) for v in copied["versions"]]
    if "items" in copied:
        copied["items"] = [dict(i) for i in copied["items"]]
    return copied


class _InterleavingContainer:
    """Wraps a container and runs a competing writer between read and write.

    Reproduces the real interleaving: A reads, B reads-modifies-writes, then A
    writes back the array it read before B existed.
    """

    def __init__(self, inner: _FakeContainer) -> None:
        self._inner = inner
        self.on_read: Any = None
        self.inner_result: Any = None

    def query_items(self, **kwargs: Any) -> list[dict[str, Any]]:
        result = self._inner.query_items(**kwargs)
        if self.on_read is not None:
            hook, self.on_read = self.on_read, None
            self.inner_result = hook()
        return result

    def upsert_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._inner.upsert_item(body, **kwargs)


def _policy_doc(policy_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(policy_id),
        "tenant_id": str(tenant_id),
        "external_id": "EXT-1",
        "name": "Test Policy",
        "status": "active",
        "jurisdiction": None,
        "category": None,
        "authority_level": 0,
        "department_scope": "all",
        "policy_type": None,
        "current_version_id": None,
        "created_by_user_id": None,
        "updated_by_user_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "versions": [],
    }


def _version_fields(policy_id: uuid.UUID, tenant_id: uuid.UUID, number: int, **over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "policy_id": policy_id,
        "tenant_id": tenant_id,
        "version_number": number,
        "content_sha256": f"sha-{number}",
        "metadata_sha256": f"meta-{number}",
        "blob_container": "policy-raw",
        "blob_name": f"doc-{number}.pdf",
        "parse_status": "pending",
    }
    fields.update(over)
    return fields


@pytest.fixture
def container() -> _FakeContainer:
    return _FakeContainer()


def test_version_create_appends_to_policy_doc(container: _FakeContainer) -> None:
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))
    repo = CosmosPolicyVersionRepository(container)

    dto = repo.create(**_version_fields(policy_id, tenant_id, 1))

    assert dto.version_number == 1
    assert dto.policy_id == policy_id
    stored = container.docs[str(policy_id)]
    assert [v["version_number"] for v in stored["versions"]] == [1]


def test_next_version_number_reads_embedded_array(container: _FakeContainer) -> None:
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))
    repo = CosmosPolicyVersionRepository(container)

    assert repo.next_version_number(policy_id=policy_id) == 1
    repo.create(**_version_fields(policy_id, tenant_id, 1))
    assert repo.next_version_number(policy_id=policy_id) == 2


def test_concurrent_version_create_does_not_lose_updates(container: _FakeContainer) -> None:
    """Two writers racing on the same policy must not destroy each other's version.

    This is the production data-loss case: the losing version is silently gone,
    the client already holds a 201, and the worker later logs
    'policy_version_not_found' and returns without surfacing an error.
    """
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))

    # Interleave the two writers the way concurrent API replicas do: both read
    # the policy document before either writes. A blocking read on the second
    # create() is what forces B's read to happen before A's write lands.
    blocked = _InterleavingContainer(container)
    repo_a = CosmosPolicyVersionRepository(blocked)
    repo_b = CosmosPolicyVersionRepository(container)

    blocked.on_read = lambda: repo_b.create(
        **_version_fields(policy_id, tenant_id, 2, content_sha256="sha-b")
    )
    dto_a = repo_a.create(**_version_fields(policy_id, tenant_id, 1, content_sha256="sha-a"))
    dto_b = blocked.inner_result

    stored_ids = {v["id"] for v in container.docs[str(policy_id)]["versions"]}
    assert str(dto_b.id) in stored_ids, "second writer's version was silently overwritten"
    assert str(dto_a.id) in stored_ids, "first writer's version was silently overwritten"
    assert len(stored_ids) == 2


def test_get_by_id_finds_version_inside_policy_doc(container: _FakeContainer) -> None:
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))
    repo = CosmosPolicyVersionRepository(container)
    created = repo.create(**_version_fields(policy_id, tenant_id, 1))

    found = repo.get_by_id(version_id=created.id)

    assert found is not None
    assert found.id == created.id
    assert found.tenant_id == tenant_id


def test_exists_duplicate_matches_on_both_hashes(container: _FakeContainer) -> None:
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))
    repo = CosmosPolicyVersionRepository(container)
    created = repo.create(**_version_fields(policy_id, tenant_id, 1))

    assert repo.exists_duplicate(
        policy_id=policy_id, content_sha256="sha-1", metadata_sha256="meta-1"
    ) == created.id
    assert (
        repo.exists_duplicate(policy_id=policy_id, content_sha256="sha-1", metadata_sha256="other")
        is None
    )


def _batch_doc(batch_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(batch_id),
        "tenant_id": str(tenant_id),
        "status": "received",
        "submitted_by_user_id": None,
        "source_system": None,
        "status_reason": None,
        "correlation_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "items": [],
    }


def test_concurrent_ingest_item_create_does_not_lose_updates(container: _FakeContainer) -> None:
    """Items nest inside the batch document and race the same way versions do."""
    batch_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_batch_doc(batch_id, tenant_id))

    blocked = _InterleavingContainer(container)
    repo_a = CosmosIngestItemRepository(blocked)
    repo_b = CosmosIngestItemRepository(container)

    blocked.on_read = lambda: repo_b.create(batch_id=batch_id, tenant_id=tenant_id, status="received")
    dto_a = repo_a.create(batch_id=batch_id, tenant_id=tenant_id, status="received")
    dto_b = blocked.inner_result

    stored = {i["id"] for i in container.docs[str(batch_id)]["items"]}
    assert {str(dto_a.id), str(dto_b.id)} == stored


def test_ingest_item_create_honours_result_policy_version_id(container: _FakeContainer) -> None:
    """Linking the item to its version at create time removes a crash window."""
    batch_id, tenant_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    container.seed(_batch_doc(batch_id, tenant_id))
    repo = CosmosIngestItemRepository(container)

    repo.create(
        batch_id=batch_id,
        tenant_id=tenant_id,
        status="received",
        result_policy_version_id=version_id,
    )

    stored = container.docs[str(batch_id)]["items"][0]
    assert stored["result_policy_version_id"] == str(version_id)


def test_set_current_marks_exactly_one_version(container: _FakeContainer) -> None:
    """Replaces the partial unique index Postgres used to enforce this."""
    policy_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    container.seed(_policy_doc(policy_id, tenant_id))
    repo = CosmosPolicyVersionRepository(container)
    v1 = repo.create(**_version_fields(policy_id, tenant_id, 1))
    v2 = repo.create(**_version_fields(policy_id, tenant_id, 2))

    repo.set_current(policy_id=policy_id, version_id=v2.id)

    doc = container.docs[str(policy_id)]
    current = [v["id"] for v in doc["versions"] if v["is_current"]]
    assert current == [str(v2.id)]
    assert doc["current_version_id"] == str(v2.id)
    assert str(v1.id) not in current


def test_rmw_gives_up_and_raises_conflict_under_permanent_contention() -> None:
    """A writer that can never win must fail loudly, not silently drop the write."""

    class _AlwaysStale:
        def query_items(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"id": "x", "_etag": '"moving-target"', "versions": []}]

        def upsert_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            raise _PreconditionFailed("always stale")

    with pytest.raises(RepositoryConflict):
        rmw(_AlwaysStale(), read=lambda: {"id": "x", "_etag": '"e"'}, mutate=lambda d: None)


# --- CosmosReferenceRepository target hydration -------------------------------


class _LookupContainer:
    """Serves reference rows or id-lookups, counting every query issued."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.query_count = 0

    def query_items(
        self, *, query: str, parameters: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.query_count += 1
        params = {p["name"]: p["value"] for p in (parameters or [])}
        if "ARRAY_CONTAINS(@ids" in query:
            return [r for r in self.rows if r["id"] in params["@ids"]]
        if "@vids" in params:
            # Mirrors the real policies query: match by id OR by an embedded version id.
            return [
                {**r, "version_ids": [v["id"] for v in r.get("versions", [])]}
                for r in self.rows
                if r["id"] in params["@pids"] or any(v["id"] in params["@vids"] for v in r.get("versions", []))
            ]
        return list(self.rows)


def _ref_doc(tenant: uuid.UUID, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(tenant),
        "reference_type": "internal_section",
        "resolution_status": "resolved",
        "matched_text": "see section 4",
        "source_section_id": str(uuid.uuid4()),
        "source_policy_version_id": str(uuid.uuid4()),
    }
    doc.update(over)
    return doc


def test_reference_listing_hydrates_target_display_fields() -> None:
    from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository

    tenant, sec_id, pol_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    refs = _LookupContainer([_ref_doc(tenant, target_section_id=str(sec_id), target_policy_id=str(pol_id))])
    sections = _LookupContainer([{"id": str(sec_id), "title": "Access control", "section_path": "4.2"}])
    policies = _LookupContainer([{"id": str(pol_id), "name": "Security Policy"}])
    repo = CosmosReferenceRepository(refs, policies, sections)

    [dto] = repo.list_for_policy_version(tenant_id=tenant, policy_version_id=uuid.uuid4())

    assert dto.target_section_title == "Access control"
    assert dto.target_section_path == "4.2"
    assert dto.target_policy_name == "Security Policy"


def test_reference_hydration_is_one_query_per_container() -> None:
    from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository

    tenant = uuid.uuid4()
    sec_ids = [uuid.uuid4() for _ in range(5)]
    pol_id = uuid.uuid4()
    refs = _LookupContainer(
        [_ref_doc(tenant, target_section_id=str(s), target_policy_id=str(pol_id)) for s in sec_ids]
    )
    sections = _LookupContainer(
        [{"id": str(s), "title": f"T{i}", "section_path": str(i)} for i, s in enumerate(sec_ids)]
    )
    policies = _LookupContainer([{"id": str(pol_id), "name": "P"}])
    repo = CosmosReferenceRepository(refs, policies, sections)

    dtos = repo.list_outbound_for_section(tenant_id=tenant, section_id=uuid.uuid4())

    assert len(dtos) == 5
    assert refs.query_count == 1
    assert sections.query_count == 1
    assert policies.query_count == 1


def test_reference_without_target_leaves_display_fields_none() -> None:
    from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository

    tenant = uuid.uuid4()
    refs = _LookupContainer([_ref_doc(tenant, reference_type="external_url", resolution_status="external")])
    sections = _LookupContainer([])
    policies = _LookupContainer([])
    repo = CosmosReferenceRepository(refs, policies, sections)

    [dto] = repo.list_inbound_for_section(tenant_id=tenant, section_id=uuid.uuid4())

    assert (dto.target_section_title, dto.target_section_path, dto.target_policy_name) == (None, None, None)
    assert sections.query_count == 1  # source display fields are looked up even without a target
    assert policies.query_count == 1  # the source policy is resolved through its version id
    assert dto.source_policy_name is None


def test_inbound_references_hydrate_source_display_fields() -> None:
    from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository

    tenant, target_sec, csf_sec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    csf_pol, nist_pol, csf_ver, nist_ver = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    refs = _LookupContainer(
        [
            _ref_doc(
                tenant,
                source_section_id=str(csf_sec),
                source_policy_version_id=str(csf_ver),
                target_section_id=str(target_sec),
                target_policy_id=str(nist_pol),
            )
        ]
    )
    # Real Cosmos section docs carry policy_version_id but no policy_id; versions are
    # embedded in the policy doc. The fakes must keep that shape or the test proves nothing.
    sections = _LookupContainer(
        [
            {"id": str(csf_sec), "title": "Supply chain", "section_path": "GV.SC-01", "policy_version_id": str(csf_ver)},
            {"id": str(target_sec), "title": "Account Management", "section_path": "AC-2", "policy_version_id": str(nist_ver)},
        ]
    )
    policies = _LookupContainer(
        [
            {"id": str(csf_pol), "name": "NIST CSF 2.0 - Govern (GV)", "versions": [{"id": str(csf_ver)}]},
            {"id": str(nist_pol), "name": "800-53 AC", "versions": [{"id": str(nist_ver)}]},
        ]
    )
    repo = CosmosReferenceRepository(refs, policies, sections)

    [dto] = repo.list_inbound_for_section(tenant_id=tenant, section_id=target_sec)

    assert dto.source_section_path == "GV.SC-01"
    assert dto.source_section_title == "Supply chain"
    assert dto.source_policy_name == "NIST CSF 2.0 - Govern (GV)"
    assert (dto.target_section_path, dto.target_policy_name) == ("AC-2", "800-53 AC")
    assert (refs.query_count, sections.query_count, policies.query_count) == (1, 1, 1)
