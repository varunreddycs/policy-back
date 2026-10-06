"""Auto-embed-on-ingest tests (GitHub issue #4, [F3]).

Prove that after the worker processes an extraction message for a policy
version, that version's sections have corresponding embedding rows — with no
manual backfill script invoked. Backend-agnostic: exercises
``_process_one_message`` against an in-memory ``RepositorySet``, the same code
path the worker runs under DB_BACKEND=cosmos.

The Azure OpenAI embedding call is mocked (a deterministic fake embedder is
injected via ``embed_sections.embed_texts``), matching the mocking style in
``test_embed_backfill.py`` — no real API is hit.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest

import apps.worker.jobs.embed_sections as embed_sections_module
from apps.worker.policy_processor import UnitOfWork, _process_one_message
from packages.db.repositories.factory import RepositorySet
from packages.db.repositories.repo_dtos import (
    PolicyDTO,
    PolicySectionDTO,
    PolicyVersionDTO,
)

_DOC = (
    b"Section 1 Overview. This policy applies broadly. See Section 2 for details.\n\n"
    b"Section 2 Details. Refer to 45 CFR 164 for the federal requirement."
)

_FAKE_VECTOR = [0.11, 0.22, 0.33]


class _FakeVersions:
    def __init__(self, version: PolicyVersionDTO) -> None:
        self._v = version
        self.statuses: list[str] = []

    def get_by_id(self, *, version_id: uuid.UUID) -> PolicyVersionDTO | None:
        return self._v if version_id == self._v.id else None

    def set_parse_status(self, *, version_id: uuid.UUID, status: str, **_: Any) -> None:
        self.statuses.append(status)
        self._v = dataclasses.replace(self._v, parse_status=status)

    def set_current(self, *, policy_id: uuid.UUID, version_id: uuid.UUID) -> None:
        self._v = dataclasses.replace(self._v, is_current=True)

    def set_extracted_blob(self, **_: Any) -> None:
        pass


class _FakePolicies:
    def __init__(self, policy: PolicyDTO) -> None:
        self._p = policy
        self.current_version_id: uuid.UUID | None = None

    def get_by_id(self, *, policy_id: uuid.UUID) -> PolicyDTO | None:
        return self._p if policy_id == self._p.id else None

    def update(
        self,
        *,
        policy_id: uuid.UUID,
        current_version_id: uuid.UUID | None = None,
        **_: Any,
    ) -> None:
        self.current_version_id = current_version_id

    def list_for_tenant(self, *, tenant_id: uuid.UUID) -> list[PolicyDTO]:
        return [self._p]


class _FakeSections:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.deleted = 0

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        self.deleted += 1
        self.rows = []
        return 0

    def bulk_insert(self, sections: list[dict[str, Any]]) -> int:
        for s in sections:
            row = dict(s)
            row.setdefault("id", uuid.uuid4())
            self.rows.append(row)
        return len(sections)

    def list_for_version(self, *, tenant_id, policy_version_id, limit=20, offset=0):
        page = self.rows[offset : offset + limit]
        return [
            PolicySectionDTO(
                id=r["id"],
                tenant_id=r["tenant_id"],
                policy_version_id=r["policy_version_id"],
                section_index=r["section_index"],
                text=r["text"],
                content_sha256=r["content_sha256"],
                section_path=r.get("section_path"),
                title=r.get("title"),
            )
            for r in page
        ]


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.deleted = 0

    def bulk_insert(self, embeddings: list[dict[str, Any]]) -> int:
        self.rows.extend(embeddings)
        return len(embeddings)

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        before = len(self.rows)
        self.rows = [
            r for r in self.rows if r["policy_version_id"] != policy_version_id
        ]
        self.deleted += 1
        return before - len(self.rows)


class _FakeIngestItems:
    def __init__(self) -> None:
        self.status_by_version: dict[uuid.UUID, str] = {}

    def set_status_by_result_version(
        self, *, policy_version_id: uuid.UUID, status: str, **_: Any
    ) -> None:
        self.status_by_version[policy_version_id] = status

    def count_active_for_batch(self, *, batch_id: uuid.UUID) -> int:
        return 0


class _FakeBatches:
    def __init__(self) -> None:
        self.status: str | None = None

    def update_status(self, *, batch_id: uuid.UUID, status: str) -> None:
        self.status = status


class _FakeReferences:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
        return 0

    def bulk_insert(self, refs: list[dict[str, Any]]) -> int:
        self.rows.extend(refs)
        return len(refs)


class _FakeBlob:
    def download_blob_bytes(self, container: str, name: str) -> bytes:
        return _DOC

    def upload_blob_bytes(
        self, container, name, data, content_type=None, overwrite=True
    ) -> str:
        return f"https://blob/{container}/{name}"


def _build_repos() -> RepositorySet:
    tenant = uuid.uuid4()
    policy_id = uuid.uuid4()
    version_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    version = PolicyVersionDTO(
        id=version_id,
        tenant_id=tenant,
        policy_id=policy_id,
        version_number=1,
        content_sha256="c",
        metadata_sha256="m",
        blob_container="policy-raw",
        blob_name="p.txt",
        parse_status="pending",
        is_current=False,
        ingest_batch_id=batch_id,
    )
    policy = PolicyDTO(
        id=policy_id,
        tenant_id=tenant,
        external_id="EXT-1",
        name="Test Policy",
        status="active",
        authority_level=80,
        department_scope="operations",
        policy_type="general",
    )
    return RepositorySet(
        policies=_FakePolicies(policy),
        versions=_FakeVersions(version),
        sections=_FakeSections(),
        embeddings=_FakeEmbeddings(),
        audit=object(),  # unused by the worker
        ingest_batches=_FakeBatches(),
        ingest_items=_FakeIngestItems(),
        references=_FakeReferences(),
    )


@pytest.fixture
def _embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "text-embedding-3-large")

    def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [list(_FAKE_VECTOR) for _ in texts]

    monkeypatch.setattr(embed_sections_module, "embed_texts", _fake_embed)


def test_worker_embeds_sections_without_manual_backfill(
    monkeypatch: pytest.MonkeyPatch, _embedding_env: None
) -> None:
    repos = _build_repos()
    uow = UnitOfWork(repos=repos, session=None)
    version = repos.versions.get_by_id(version_id=repos.versions._v.id)  # type: ignore[attr-defined]
    assert version is not None

    _process_one_message(
        uow=uow,
        blob_service=_FakeBlob(),  # type: ignore[arg-type]
        policy_version_id=version.id,
        correlation_id="corr-embed",
        extracted_container="policy-extracted",
    )

    sections = repos.sections  # type: ignore[assignment]
    embeddings = repos.embeddings  # type: ignore[assignment]

    # Version reached READY and sections were persisted.
    final = repos.versions.get_by_id(version_id=version.id)
    assert final is not None
    assert final.parse_status == "ready"
    assert len(sections.rows) > 0  # type: ignore[attr-defined]

    # Every persisted section has exactly one embedding row, keyed to it.
    assert len(embeddings.rows) == len(sections.rows)  # type: ignore[attr-defined]
    section_ids = {r["id"] for r in sections.rows}  # type: ignore[attr-defined]
    embedded_section_ids = {r["policy_section_id"] for r in embeddings.rows}  # type: ignore[attr-defined]
    assert embedded_section_ids == section_ids

    # Ranking metadata was carried from the policy/version onto the embeddings.
    for row in embeddings.rows:  # type: ignore[attr-defined]
        assert row["policy_version_id"] == version.id
        assert row["authority_level"] == 80
        assert row["department_scope"] == "operations"
        assert row["policy_type"] == "general"
        assert row["embedding"] == _FAKE_VECTOR


def test_reprocessing_is_idempotent_no_duplicate_embeddings(
    monkeypatch: pytest.MonkeyPatch, _embedding_env: None
) -> None:
    repos = _build_repos()
    version = repos.versions.get_by_id(version_id=repos.versions._v.id)  # type: ignore[attr-defined]
    assert version is not None

    for _ in range(2):
        # Reset to a re-processable state (a retried queue message).
        repos.versions._v = dataclasses.replace(  # type: ignore[attr-defined]
            repos.versions._v,
            parse_status="pending",  # type: ignore[attr-defined]
        )
        uow = UnitOfWork(repos=repos, session=None)
        _process_one_message(
            uow=uow,
            blob_service=_FakeBlob(),  # type: ignore[arg-type]
            policy_version_id=version.id,
            correlation_id="corr-retry",
            extracted_container="policy-extracted",
        )

    sections = repos.sections  # type: ignore[assignment]
    embeddings = repos.embeddings  # type: ignore[assignment]

    # No duplicates after two passes: one embedding per current section.
    assert len(embeddings.rows) == len(sections.rows)  # type: ignore[attr-defined]
    assert (
        embeddings.deleted >= 2
    )  # delete-then-insert ran on each pass  # type: ignore[attr-defined]


def test_missing_embedding_config_skips_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT",
    ):
        monkeypatch.delenv(var, raising=False)

    def _boom(texts: list[str]) -> list[list[float]]:
        raise AssertionError("embedder must not be called when config is absent")

    monkeypatch.setattr(embed_sections_module, "embed_texts", _boom)

    repos = _build_repos()
    version = repos.versions.get_by_id(version_id=repos.versions._v.id)  # type: ignore[attr-defined]
    assert version is not None

    uow = UnitOfWork(repos=repos, session=None)
    _process_one_message(
        uow=uow,
        blob_service=_FakeBlob(),  # type: ignore[arg-type]
        policy_version_id=version.id,
        correlation_id="corr-noconfig",
        extracted_container="policy-extracted",
    )

    # Ingestion still completed; embedding was skipped, not crashed.
    final = repos.versions.get_by_id(version_id=version.id)
    assert final is not None
    assert final.parse_status == "ready"
    assert len(repos.sections.rows) > 0  # type: ignore[attr-defined]
    assert len(repos.embeddings.rows) == 0  # type: ignore[attr-defined]
