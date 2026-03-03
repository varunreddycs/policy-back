from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from azure.core.exceptions import AzureError
from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.session import get_sessionmaker
from models import IngestBatch, IngestItem, ParseStatus, Policy, PolicySection, PolicyVersion, sha256_hex
from services.blob_service import BlobService

logger = logging.getLogger(__name__)


def _load_dotenv_if_present() -> None:
	try:
		from dotenv import load_dotenv  # type: ignore

		load_dotenv()
	except Exception:
		return


_load_dotenv_if_present()


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
			os.getenv("AZURE_STORAGE_QUEUE_ACCOUNT_URL")
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
		# If user provided the blob account URL, convert to queue endpoint.
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

	# Support both our canonical envelope and a bare payload.
	if isinstance(payload, dict) and "type" in payload and "data" in payload and isinstance(payload["data"], dict):
		data = payload["data"]
		msg_type = payload.get("type")
		if msg_type and msg_type != "policy.process.requested":
			raise ValueError(f"Unexpected message type: {msg_type}")
		return data
	if isinstance(payload, dict):
		return payload
	raise ValueError("Invalid payload shape")


def _extract_sections_stub(text: str) -> list[dict[str, Any]]:
	"""A deterministic, minimal extractor stub.

	Splits into a single section or a few chunked sections, so downstream is exercised.
	"""
	clean = (text or "").strip()
	if not clean:
		return [
			{
				"section_key": "main",
				"title": "Main",
				"start_offset": 0,
				"end_offset": 0,
				"text": "",
				"metadata": {},
			}
		]

	chunk_size = 4000
	sections: list[dict[str, Any]] = []
	for idx, start in enumerate(range(0, len(clean), chunk_size), start=1):
		end = min(len(clean), start + chunk_size)
		sections.append(
			{
				"section_key": f"chunk-{idx}",
				"title": f"Chunk {idx}",
				"start_offset": start,
				"end_offset": end,
				"text": clean[start:end],
				"metadata": {"extractor": "stub", "chunk_size": chunk_size},
			}
		)
	return sections


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


def _process_one_message(
	*,
	db: Session,
	blob_service: BlobService,
	policy_version_id: uuid.UUID,
	correlation_id: str | None,
	extracted_container: str,
) -> None:
	# Fetch version + policy
	version = db.execute(select(PolicyVersion).where(PolicyVersion.id == policy_version_id)).scalar_one_or_none()
	if version is None:
		logger.warning(
			"worker.policy_version_not_found",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		return

	policy = db.execute(select(Policy).where(Policy.id == version.policy_id)).scalar_one_or_none()
	if policy is None:
		logger.warning(
			"worker.policy_not_found",
			extra={"policy_version_id": str(policy_version_id), "policy_id": str(version.policy_id), "correlation_id": correlation_id},
		)
		return

	if version.parse_status == ParseStatus.READY:
		logger.info(
			"worker.policy_version_already_ready",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		# Ensure current pointers are consistent even if previous run partially succeeded.
		if not version.is_current:
			try:
				db.execute(update(PolicyVersion).where(PolicyVersion.policy_id == policy.id).values(is_current=False))
				db.execute(
					update(PolicyVersion).where(PolicyVersion.id == version.id).values(is_current=True)
				)
				db.execute(update(Policy).where(Policy.id == policy.id).values(current_version_id=version.id))
				db.commit()
			except SQLAlchemyError:
				db.rollback()
				raise
		return

	# Mark as processing
	try:
		version.parse_status = ParseStatus.PROCESSING
		version.parse_status_updated_at = datetime.now(timezone.utc)
		version.parse_error_code = None
		version.parse_error_message = None
		# Update ingest item/batch for demo traceability.
		if version.ingest_batch_id:
			db.execute(
				update(IngestItem)
				.where(IngestItem.result_policy_version_id == version.id)
				.values(status="processing", updated_at=func.now())
			)
			db.execute(
				update(IngestBatch)
				.where(IngestBatch.id == version.ingest_batch_id)
				.values(status="processing", updated_at=func.now())
			)
		db.add(version)
		db.commit()
	except SQLAlchemyError:
		db.rollback()
		raise

	# Download source bytes and create extracted JSON
	try:
		source_bytes = blob_service.download_blob_bytes(version.blob_container, version.blob_name)
		try:
			source_text = source_bytes.decode("utf-8", errors="replace")
		except Exception:
			source_text = ""

		sections_payload = _extract_sections_stub(source_text)
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
		try:
			version.parse_status = ParseStatus.FAILED
			version.parse_status_updated_at = datetime.now(timezone.utc)
			version.parse_error_code = "extraction_failed"
			version.parse_error_message = str(exc)
			if version.ingest_batch_id:
				db.execute(
					update(IngestItem)
					.where(IngestItem.result_policy_version_id == version.id)
					.values(status="failed", error_code="extraction_failed", error_message=str(exc), updated_at=func.now())
				)
				# If all items in the batch are terminal, mark batch failed.
				remaining = db.execute(
					select(func.count(IngestItem.id)).where(
						IngestItem.batch_id == version.ingest_batch_id,
						IngestItem.status.in_(["received", "queued", "processing"]),
					)
				).scalar_one()
				if int(remaining) == 0:
					db.execute(
						update(IngestBatch)
						.where(IngestBatch.id == version.ingest_batch_id)
						.values(status="failed", updated_at=func.now())
					)
			db.add(version)
			db.commit()
		except SQLAlchemyError:
			db.rollback()
		raise exc

	# Persist sections + finalize status/current pointers
	try:
		# Idempotency: clear any existing sections for this version.
		db.execute(delete(PolicySection).where(PolicySection.policy_version_id == version.id))
		for idx, section in enumerate(sections_payload, start=0):
			db.add(
				PolicySection(
					tenant_id=version.tenant_id,
					policy_version_id=version.id,
					section_index=idx,
					section_path=str(section.get("section_key") or f"section-{idx}"),
					title=str(section.get("title") or ""),
					text=str(section.get("text") or ""),
					start_offset=int(section.get("start_offset") or 0),
					end_offset=int(section.get("end_offset") or 0),
					content_sha256=sha256_hex(str(section.get("text") or "").encode("utf-8")),
				)
			)

		# Save extracted artifact details on version (do not mutate metadata_json, which must match metadata_sha256)
		version.extracted_blob_container = extracted_container
		version.extracted_blob_name = extracted_blob_path
		version.extracted_blob_uri = extracted_uri

		version.parse_status = ParseStatus.READY
		version.parse_status_updated_at = datetime.now(timezone.utc)

		# Flip current pointer (DB has partial unique index on is_current)
		db.execute(update(PolicyVersion).where(PolicyVersion.policy_id == policy.id).values(is_current=False))
		version.is_current = True
		db.add(version)
		policy.current_version_id = version.id
		db.add(policy)
		if version.ingest_batch_id:
			db.execute(
				update(IngestItem)
				.where(IngestItem.result_policy_version_id == version.id)
				.values(status="completed", updated_at=func.now())
			)
			remaining = db.execute(
				select(func.count(IngestItem.id)).where(
					IngestItem.batch_id == version.ingest_batch_id,
					IngestItem.status.in_(["received", "queued", "processing"]),
				)
			).scalar_one()
			if int(remaining) == 0:
				db.execute(
					update(IngestBatch)
					.where(IngestBatch.id == version.ingest_batch_id)
					.values(status="completed", updated_at=func.now())
				)
		db.commit()
		logger.info(
			"worker.policy_version_ready",
			extra={
				"policy_version_id": str(version.id),
				"policy_id": str(policy.id),
				"sections": len(sections_payload),
				"correlation_id": correlation_id,
			},
		)
	except SQLAlchemyError:
		db.rollback()
		raise


def run_worker_forever() -> None:
	config = WorkerConfig.from_env()
	logger.info(
		"worker.starting",
		extra={
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
		credential = AzureNamedKeyCredential(account_name, account_key)
		queue_client = QueueClient(
			account_url=config.queue_url,
			queue_name=config.queue_name,
			credential=credential,
			api_version=api_version,
		)
	else:
		credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
		queue_client = QueueClient(
			account_url=config.queue_url,
			queue_name=config.queue_name,
			credential=credential,
			api_version=api_version,
		)
	blob_service = BlobService()
	SessionLocal = get_sessionmaker()

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
					dequeue_count = getattr(msg, "dequeue_count", None)
					try:
						payload = _parse_queue_payload(msg.content)
						policy_version_id = _ensure_uuid(payload.get("policy_version_id"), "policy_version_id")
						correlation_id = payload.get("correlation_id")

						with SessionLocal() as db:
							_process_one_message(
								db=db,
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
								"dequeue_count": dequeue_count,
							},
						)
					except Exception:
						logger.exception(
							"worker.message_processing_failed",
							extra={"dequeue_count": dequeue_count},
						)
						# Let the message become visible again for retry.

			if not got_any:
				time.sleep(config.poll_seconds)
		except AzureError:
			logger.exception("worker.queue_receive_failed")
			time.sleep(5)
		except Exception:
			logger.exception("worker.unhandled_error")
			time.sleep(5)


if __name__ == "__main__":
	run_worker_forever()
