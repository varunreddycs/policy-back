"""Backend-agnostic worker tests.

Exercise apps.worker.policy_processor._process_one_message against an in-memory
RepositorySet (no SQLAlchemy session, no Cosmos client) — the same code path
the worker runs under DB_BACKEND=cosmos.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

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

	def update(self, *, policy_id: uuid.UUID, current_version_id: uuid.UUID | None = None, **_: Any) -> None:
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
		self.rows.extend(sections)
		return len(sections)

	def list_for_version(self, *, tenant_id, policy_version_id, limit=20, offset=0):
		page = self.rows[offset : offset + limit]
		return [
			PolicySectionDTO(
				id=r.get("id", uuid.uuid4()),
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


class _FakeIngestItems:
	def __init__(self) -> None:
		self.status_by_version: dict[uuid.UUID, str] = {}

	def set_status_by_result_version(self, *, policy_version_id: uuid.UUID, status: str, **_: Any) -> None:
		self.status_by_version[policy_version_id] = status

	def count_active_for_batch(self, *, batch_id: uuid.UUID) -> int:
		return 0  # this is the only item; it just completed


class _FakeBatches:
	def __init__(self) -> None:
		self.status: str | None = None

	def update_status(self, *, batch_id: uuid.UUID, status: str) -> None:
		self.status = status


class _FakeReferences:
	def __init__(self) -> None:
		self.rows: list[dict[str, Any]] = []
		self.deleted = 0

	def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
		self.deleted += 1
		return 0

	def bulk_insert(self, refs: list[dict[str, Any]]) -> int:
		self.rows.extend(refs)
		return len(refs)


class _FakeBlob:
	def download_blob_bytes(self, container: str, name: str) -> bytes:
		return _DOC

	def upload_blob_bytes(self, container, name, data, content_type=None, overwrite=True) -> str:
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
	)
	return RepositorySet(
		policies=_FakePolicies(policy),
		versions=_FakeVersions(version),
		sections=_FakeSections(),
		embeddings=object(),  # unused by the worker
		audit=object(),  # unused by the worker
		ingest_batches=_FakeBatches(),
		ingest_items=_FakeIngestItems(),
		references=_FakeReferences(),
	)


def test_process_one_message_marks_ready_and_persists_sections() -> None:
	repos = _build_repos()
	uow = UnitOfWork(repos=repos, session=None)
	version = repos.versions.get_by_id(version_id=repos.versions._v.id)  # type: ignore[attr-defined]
	assert version is not None

	_process_one_message(
		uow=uow,
		blob_service=_FakeBlob(),  # type: ignore[arg-type]
		policy_version_id=version.id,
		correlation_id="corr-1",
		extracted_container="policy-extracted",
	)

	# Version ended READY and current.
	final = repos.versions.get_by_id(version_id=version.id)
	assert final is not None
	assert final.parse_status == "ready"
	assert final.is_current is True
	assert repos.versions.statuses == ["processing", "ready"]  # type: ignore[attr-defined]

	# Sections were re-written.
	assert repos.sections.deleted == 1  # type: ignore[attr-defined]
	assert len(repos.sections.rows) > 0  # type: ignore[attr-defined]

	# Policy current_version_id advanced.
	assert repos.policies.current_version_id == version.id  # type: ignore[attr-defined]

	# Ingest tracking flipped to completed.
	assert repos.ingest_items.status_by_version[version.id] == "completed"  # type: ignore[attr-defined]
	assert repos.ingest_batches.status == "completed"  # type: ignore[attr-defined]

	# References (advisory) ran: delete-then-insert; "45 CFR 164" resolves external.
	assert repos.references.deleted == 1  # type: ignore[attr-defined]
	ext = [r for r in repos.references.rows if r["resolution_status"] == "external"]  # type: ignore[attr-defined]
	assert ext, "expected an external_authority reference for the CFR citation"
