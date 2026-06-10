from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient

from packages.db.models.policy_models import ParseStatus, sha256_hex
from packages.db.repositories.factory import RepositorySet, build_repositories
from packages.db.repositories.repo_dtos import (
	PolicyDTO,
	PolicySectionDTO,
	PolicyVersionDTO,
)
from packages.extraction.extractor import extract_sections
from packages.extraction.reference_resolver import extract_and_resolve_for_sections
from packages.storage.blob_service import BlobService


logger = logging.getLogger(__name__)


def _strip_nul(text: str) -> str:
	# Postgres TEXT cannot contain NUL bytes; harmless to strip for Cosmos too.
	return (text or "").replace("\x00", "")


def _status_value(status: Any) -> str:
	"""Normalize a parse_status (enum member or raw string) to its string value."""
	return str(getattr(status, "value", status))


def _load_dotenv_if_present() -> None:
	try:
		from dotenv import load_dotenv  # type: ignore

		load_dotenv()
	except Exception:
		return


_load_dotenv_if_present()


# ---------------------------------------------------------------------------
# Backend abstraction — the worker is DB-agnostic via the repository layer.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendContext:
	"""Holds the resources needed to build a RepositorySet per message."""

	backend: str
	sessionmaker: Any = None
	cosmos_client: Any = None
	cosmos_database: str = "policydb"

	@staticmethod
	def from_env() -> "BackendContext":
		backend = os.getenv("DB_BACKEND", "postgresql").strip().lower()
		if backend == "cosmos":
			from packages.db.repositories.cosmos.cosmos_client_factory import (
				create_cosmos_client,
			)

			return BackendContext(
				backend="cosmos",
				cosmos_client=create_cosmos_client(),
				cosmos_database=os.getenv("COSMOS_DATABASE", "policydb"),
			)

		from packages.db.session import get_sessionmaker

		return BackendContext(backend="postgresql", sessionmaker=get_sessionmaker())


@dataclass
class UnitOfWork:
	"""A repository set plus transaction control.

	For PostgreSQL, ``commit``/``rollback`` delegate to the SQLAlchemy session.
	For Cosmos DB there is no multi-document transaction, so each repository
	write is durable immediately and commit/rollback are no-ops.
	"""

	repos: RepositorySet
	session: Any = None

	def commit(self) -> None:
		if self.session is not None:
			self.session.commit()

	def rollback(self) -> None:
		if self.session is not None:
			self.session.rollback()


@contextmanager
def unit_of_work(ctx: BackendContext) -> Iterator[UnitOfWork]:
	if ctx.backend == "cosmos":
		repos = build_repositories(
			backend="cosmos",
			cosmos_client=ctx.cosmos_client,
			cosmos_database=ctx.cosmos_database,
		)
		yield UnitOfWork(repos=repos, session=None)
		return

	session = ctx.sessionmaker()
	try:
		yield UnitOfWork(repos=build_repositories(session=session), session=session)
	finally:
		session.close()


@dataclass(frozen=True)
class WorkerConfig:
	queue_url: str
	queue_name: str
	extracted_container: str
	poll_seconds: float
	visibility_timeout: int
	max_messages: int

	@staticmethod
	def from_env() -> "WorkerConfig":
		queue_name = os.getenv("AZURE_POLICY_EXTRACTION_QUEUE_NAME") or os.getenv("AZURE_STORAGE_QUEUE_NAME")
		queue_url = (
			os.getenv("AZURE_STORAGE_QUEUE_ACCOUNT_URL_INTERNAL")
			or os.getenv("AZURE_STORAGE_QUEUE_ACCOUNT_URL")
			or os.getenv("AZURE_STORAGE_QUEUE_URL")
			or os.getenv("AZURE_STORAGE_ACCOUNT_URL")
		)
		extracted_container = os.getenv("AZURE_POLICY_EXTRACTED_CONTAINER", "policy-extracted")
		poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "2"))
		visibility_timeout = int(os.getenv("WORKER_VISIBILITY_TIMEOUT_SECONDS", "60"))
		max_messages = int(os.getenv("WORKER_MAX_MESSAGES", "8"))

		if not queue_name:
			raise ValueError(
				"Missing queue configuration. Set AZURE_POLICY_EXTRACTION_QUEUE_NAME (preferred) or AZURE_STORAGE_QUEUE_NAME."
			)
		if not queue_url:
			raise ValueError(
				"Missing queue account URL. Set AZURE_STORAGE_QUEUE_ACCOUNT_URL (preferred) or AZURE_STORAGE_QUEUE_URL."
			)
		if ".blob.core." in queue_url:
			host = queue_url.split("//", 1)[1].split("/", 1)[0]
			account_name = host.split(".", 1)[0]
			queue_url = f"https://{account_name}.queue.core.windows.net"
		return WorkerConfig(
			queue_url=queue_url,
			queue_name=queue_name,
			extracted_container=extracted_container,
			poll_seconds=poll_seconds,
			visibility_timeout=visibility_timeout,
			max_messages=max_messages,
		)


def _utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def _parse_queue_payload(raw: str) -> dict[str, Any]:
	try:
		payload = json.loads(raw)
	except json.JSONDecodeError as exc:
		raise ValueError("Invalid JSON payload") from exc

	if isinstance(payload, dict) and "type" in payload and "data" in payload and isinstance(payload["data"], dict):
		data = payload["data"]
		msg_type = payload.get("type")
		if msg_type and msg_type != "policy.process.requested":
			raise ValueError(f"Unexpected message type: {msg_type}")
		return data
	if isinstance(payload, dict):
		return payload
	raise ValueError("Invalid payload shape")


def _extract_sections_for_blob(*, blob_name: str, source_bytes: bytes) -> list[dict[str, Any]]:
	sections = extract_sections(filename=blob_name, content_bytes=source_bytes)
	return [
		{
			"section_key": section.section_key,
			"title": section.title,
			"start_offset": section.start_offset,
			"end_offset": section.end_offset,
			"text": _strip_nul(section.text),
			"metadata": section.metadata,
		}
		for section in sections
	]


def _ensure_uuid(value: Any, field_name: str) -> uuid.UUID:
	if isinstance(value, uuid.UUID):
		return value
	if isinstance(value, str):
		try:
			return uuid.UUID(value)
		except ValueError as exc:
			raise ValueError(f"Invalid UUID for {field_name}") from exc
	raise ValueError(f"Invalid type for {field_name}")


def _make_extracted_blob_path(tenant_id: uuid.UUID, policy_id: uuid.UUID, policy_version_id: uuid.UUID) -> str:
	return f"tenants/{tenant_id}/policies/{policy_id}/versions/{policy_version_id}/extracted.json"


def _all_sections_for_version(
	repos: RepositorySet,
	*,
	tenant_id: uuid.UUID,
	policy_version_id: uuid.UUID,
	page_size: int = 200,
) -> list[PolicySectionDTO]:
	"""Page through every section of a version (used for reference resolution)."""
	out: list[PolicySectionDTO] = []
	offset = 0
	while True:
		batch = repos.sections.list_for_version(
			tenant_id=tenant_id,
			policy_version_id=policy_version_id,
			limit=page_size,
			offset=offset,
		)
		out.extend(batch)
		if len(batch) < page_size:
			break
		offset += page_size
	return out


def _mark_policy_version_failed(
	*,
	uow: UnitOfWork,
	version: PolicyVersionDTO,
	error_code: str,
	error_message: str,
) -> None:
	repos = uow.repos
	try:
		repos.versions.set_parse_status(
			version_id=version.id,
			status=ParseStatus.FAILED.value,
			error_code=error_code,
			error_message=error_message,
		)
		if version.ingest_batch_id:
			repos.ingest_items.set_status_by_result_version(
				policy_version_id=version.id,
				status="failed",
				error_code=error_code,
				error_message=error_message,
			)
			if repos.ingest_items.count_active_for_batch(batch_id=version.ingest_batch_id) == 0:
				repos.ingest_batches.update_status(batch_id=version.ingest_batch_id, status="failed")
		uow.commit()
	except Exception:
		logger.exception(
			"worker.mark_failed_error",
			extra={"policy_version_id": str(version.id)},
		)
		uow.rollback()


def _make_current(*, repos: RepositorySet, policy: PolicyDTO, version_id: uuid.UUID) -> None:
	# set_current clears is_current on siblings (and, on Cosmos, also sets the
	# policy's current_version_id). update() covers current_version_id on PG.
	repos.versions.set_current(policy_id=policy.id, version_id=version_id)
	repos.policies.update(policy_id=policy.id, current_version_id=version_id)


def _process_one_message(
	*,
	uow: UnitOfWork,
	blob_service: BlobService,
	policy_version_id: uuid.UUID,
	correlation_id: str | None,
	extracted_container: str,
) -> None:
	repos = uow.repos
	version = repos.versions.get_by_id(version_id=policy_version_id)
	if version is None:
		logger.warning(
			"worker.policy_version_not_found",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		return

	policy = repos.policies.get_by_id(policy_id=version.policy_id)
	if policy is None:
		logger.warning(
			"worker.policy_not_found",
			extra={
				"policy_version_id": str(policy_version_id),
				"policy_id": str(version.policy_id),
				"correlation_id": correlation_id,
			},
		)
		return

	if _status_value(version.parse_status) == ParseStatus.READY.value:
		logger.info(
			"worker.policy_version_already_ready",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		if not version.is_current:
			try:
				_make_current(repos=repos, policy=policy, version_id=version.id)
				uow.commit()
			except Exception:
				uow.rollback()
				raise
		return

	# Mark processing.
	try:
		repos.versions.set_parse_status(version_id=version.id, status=ParseStatus.PROCESSING.value)
		if version.ingest_batch_id:
			repos.ingest_items.set_status_by_result_version(
				policy_version_id=version.id, status="processing"
			)
			repos.ingest_batches.update_status(batch_id=version.ingest_batch_id, status="processing")
		uow.commit()
	except Exception:
		uow.rollback()
		raise

	# Extract + persist the extracted artifact to blob storage.
	try:
		source_bytes = blob_service.download_blob_bytes(version.blob_container, version.blob_name)
		sections_payload = _extract_sections_for_blob(blob_name=version.blob_name, source_bytes=source_bytes)
		extracted_doc = {
			"policy_version_id": str(version.id),
			"policy_id": str(policy.id),
			"tenant_id": str(version.tenant_id),
			"correlation_id": correlation_id,
			"created_at": _utc_now_iso(),
			"sections": sections_payload,
		}
		extracted_bytes = json.dumps(extracted_doc, ensure_ascii=False).encode("utf-8")
		extracted_blob_path = _make_extracted_blob_path(version.tenant_id, policy.id, version.id)
		extracted_uri = blob_service.upload_blob_bytes(
			extracted_container,
			extracted_blob_path,
			extracted_bytes,
			content_type="application/json",
			overwrite=True,
		)
	except Exception as exc:
		logger.exception(
			"worker.extraction_failed",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		uow.rollback()
		_mark_policy_version_failed(
			uow=uow, version=version, error_code="extraction_failed", error_message=str(exc)
		)
		# Don't re-raise: permanent failure, let the caller delete the queue message.
		return

	# Persist sections + flip the version to READY/current.
	try:
		repos.sections.delete_for_version(policy_version_id=version.id)
		section_dicts = [
			{
				"tenant_id": version.tenant_id,
				"policy_version_id": version.id,
				"section_index": idx,
				"section_path": str(section.get("section_key") or f"section-{idx}"),
				"title": str(section.get("title") or ""),
				"text": _strip_nul(str(section.get("text") or "")),
				"start_offset": int(section.get("start_offset") or 0),
				"end_offset": int(section.get("end_offset") or 0),
				"content_sha256": sha256_hex(str(section.get("text") or "").encode("utf-8")),
			}
			for idx, section in enumerate(sections_payload)
		]
		repos.sections.bulk_insert(section_dicts)

		repos.versions.set_extracted_blob(
			version_id=version.id,
			extracted_blob_container=extracted_container,
			extracted_blob_name=extracted_blob_path,
			extracted_blob_uri=extracted_uri,
		)
		repos.versions.set_parse_status(version_id=version.id, status=ParseStatus.READY.value)
		_make_current(repos=repos, policy=policy, version_id=version.id)

		if version.ingest_batch_id:
			repos.ingest_items.set_status_by_result_version(
				policy_version_id=version.id, status="completed"
			)
			if repos.ingest_items.count_active_for_batch(batch_id=version.ingest_batch_id) == 0:
				repos.ingest_batches.update_status(batch_id=version.ingest_batch_id, status="completed")
		uow.commit()
		logger.info(
			"worker.policy_version_ready",
			extra={
				"policy_version_id": str(version.id),
				"policy_id": str(policy.id),
				"sections": len(sections_payload),
				"correlation_id": correlation_id,
			},
		)
	except Exception as exc:
		logger.exception(
			"worker.persistence_failed",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		uow.rollback()
		_mark_policy_version_failed(
			uow=uow, version=version, error_code="persist_failed", error_message=str(exc)
		)
		return

	# Phase 3.1 — extract cross-references from the freshly persisted sections.
	# Advisory: a failure here must not regress ingestion, so it runs in its own
	# try/except with an independent commit.
	try:
		sections = _all_sections_for_version(
			repos, tenant_id=version.tenant_id, policy_version_id=version.id
		)
		tenant_policies = [
			(p.id, p.name) for p in repos.policies.list_for_tenant(tenant_id=version.tenant_id)
		]
		repos.references.delete_for_policy_version(policy_version_id=version.id)
		ref_dicts = extract_and_resolve_for_sections(
			sections=sections,
			source_policy_id=policy.id,
			tenant_policies=tenant_policies,
		)
		repos.references.bulk_insert(ref_dicts)
		uow.commit()
		logger.info(
			"worker.references_extracted",
			extra={
				"policy_version_id": str(version.id),
				"reference_count": len(ref_dicts),
				"correlation_id": correlation_id,
			},
		)
	except Exception:
		logger.exception(
			"worker.reference_extraction_failed",
			extra={"policy_version_id": str(version.id), "correlation_id": correlation_id},
		)
		uow.rollback()


def run_worker_forever() -> None:
	config = WorkerConfig.from_env()
	backend_ctx = BackendContext.from_env()
	logger.info(
		"worker.starting",
		extra={
			"backend": backend_ctx.backend,
			"queue_url": config.queue_url,
			"queue_name": config.queue_name,
			"poll_seconds": config.poll_seconds,
			"visibility_timeout": config.visibility_timeout,
			"max_messages": config.max_messages,
			"extracted_container": config.extracted_container,
		},
	)

	api_version = os.getenv("AZURE_STORAGE_API_VERSION")
	account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
	account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
	if account_key:
		if not account_name:
			raise ValueError("Missing AZURE_STORAGE_ACCOUNT_NAME for shared key auth")
		credential: Any = AzureNamedKeyCredential(account_name, account_key)
	else:
		credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
	queue_client = QueueClient(
		account_url=config.queue_url,
		queue_name=config.queue_name,
		credential=credential,
		api_version=api_version,
	)
	blob_service = BlobService()

	while True:
		try:
			messages = queue_client.receive_messages(
				messages_per_page=config.max_messages,
				visibility_timeout=config.visibility_timeout,
			)
			got_any = False
			for msg_page in messages.by_page():
				for msg in msg_page:
					got_any = True
					try:
						payload = _parse_queue_payload(msg.content)
						policy_version_id = _ensure_uuid(payload.get("policy_version_id"), "policy_version_id")
						correlation_id = payload.get("correlation_id")

						with unit_of_work(backend_ctx) as uow:
							_process_one_message(
								uow=uow,
								blob_service=blob_service,
								policy_version_id=policy_version_id,
								correlation_id=correlation_id,
								extracted_container=config.extracted_container,
							)

						queue_client.delete_message(msg)
						logger.info(
							"worker.message_deleted",
							extra={
								"policy_version_id": str(policy_version_id),
								"correlation_id": correlation_id,
							},
						)
					except Exception:
						logger.exception("worker.message_processing_failed")
						# Leave message; it will become visible again.

			if not got_any:
				time.sleep(config.poll_seconds)
		except Exception:
			logger.exception("worker.poll_failed")
			time.sleep(max(1.0, config.poll_seconds))
