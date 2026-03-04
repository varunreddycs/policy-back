from __future__ import annotations

import json
import logging
import os
import time
import uuid
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from packages.db.models.policy_models import (
	IngestBatch,
	IngestItem,
	ParseStatus,
	Policy,
	PolicySection,
	PolicyVersion,
	sha256_hex,
)
from packages.db.session import get_sessionmaker
from packages.storage.blob_service import BlobService


logger = logging.getLogger(__name__)


def _strip_nul(text: str) -> str:
	# Postgres TEXT cannot contain NUL bytes.
	return (text or "").replace("\x00", "")


def _extract_text_from_txt(source_bytes: bytes) -> str:
	# UTF-8 first, then fall back to replacement.
	try:
		return source_bytes.decode("utf-8-sig")
	except Exception:
		return source_bytes.decode("utf-8", errors="replace")


def _extract_text_from_docx(source_bytes: bytes) -> str:
	# Minimal DOCX text extractor without external deps.
	# DOCX is a ZIP; main content is in word/document.xml
	with zipfile.ZipFile(io.BytesIO(source_bytes)) as zf:
		xml_bytes = zf.read("word/document.xml")
	root = ElementTree.fromstring(xml_bytes)
	ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
	paragraphs: list[str] = []
	for p in root.findall(".//w:p", ns):
		parts = []
		for t in p.findall(".//w:t", ns):
			if t.text:
				parts.append(t.text)
		para = "".join(parts).strip()
		if para:
			paragraphs.append(para)
	return "\n".join(paragraphs)


def _extract_text_from_pdf(source_bytes: bytes) -> str:
	try:
		from pypdf import PdfReader  # type: ignore
	except Exception as exc:  # pragma: no cover
		raise RuntimeError("PDF extraction requires 'pypdf' dependency") from exc

	reader = PdfReader(io.BytesIO(source_bytes))
	pages_text: list[str] = []
	for page in reader.pages:
		try:
			pages_text.append(page.extract_text() or "")
		except Exception:
			pages_text.append("")
	return "\n".join([t for t in pages_text if t])


def _extract_text_from_blob(*, blob_name: str, source_bytes: bytes) -> str:
	ext = os.path.splitext(blob_name or "")[1].lower()
	if ext in {".txt", ".md"}:
		return _extract_text_from_txt(source_bytes)
	if ext == ".docx":
		return _extract_text_from_docx(source_bytes)
	if ext == ".pdf":
		return _extract_text_from_pdf(source_bytes)
	# Default: try to decode as UTF-8 but don't pretend it is safe for binary formats.
	return _extract_text_from_txt(source_bytes)


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


def _extract_sections_stub(text: str) -> list[dict[str, Any]]:
	clean = _strip_nul(text).strip()
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


def _mark_policy_version_failed(
	*,
	db: Session,
	version: PolicyVersion,
	error_code: str,
	error_message: str,
) -> None:
	version.parse_status = ParseStatus.FAILED
	version.parse_status_updated_at = datetime.now(timezone.utc)
	version.parse_error_code = error_code
	version.parse_error_message = error_message
	if version.ingest_batch_id:
		db.execute(
			update(IngestItem)
			.where(IngestItem.result_policy_version_id == version.id)
			.values(
				status="failed",
				error_code=error_code,
				error_message=error_message,
				updated_at=func.now(),
			)
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
				.values(status="failed", updated_at=func.now())
			)
	db.add(version)
	db.commit()


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
			extra={
				"policy_version_id": str(policy_version_id),
				"policy_id": str(version.policy_id),
				"correlation_id": correlation_id,
			},
		)
		return

	if version.parse_status == ParseStatus.READY:
		logger.info(
			"worker.policy_version_already_ready",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		if not version.is_current:
			try:
				db.execute(update(PolicyVersion).where(PolicyVersion.policy_id == policy.id).values(is_current=False))
				db.execute(update(PolicyVersion).where(PolicyVersion.id == version.id).values(is_current=True))
				db.execute(update(Policy).where(Policy.id == policy.id).values(current_version_id=version.id))
				db.commit()
			except SQLAlchemyError:
				db.rollback()
				raise
		return

	try:
		version.parse_status = ParseStatus.PROCESSING
		version.parse_status_updated_at = datetime.now(timezone.utc)
		version.parse_error_code = None
		version.parse_error_message = None
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

	try:
		source_bytes = blob_service.download_blob_bytes(version.blob_container, version.blob_name)
		source_text = _extract_text_from_blob(blob_name=version.blob_name, source_bytes=source_bytes)

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
			_mark_policy_version_failed(
				db=db,
				version=version,
				error_code="extraction_failed",
				error_message=str(exc),
			)
		except SQLAlchemyError:
			db.rollback()
		# Don't re-raise: treat as a permanent failure and let the caller delete the queue message.
		return

	try:
		db.execute(delete(PolicySection).where(PolicySection.policy_version_id == version.id))
		for idx, section in enumerate(sections_payload, start=0):
			db.add(
				PolicySection(
					tenant_id=version.tenant_id,
					policy_version_id=version.id,
					section_index=idx,
					section_path=str(section.get("section_key") or f"section-{idx}"),
					title=str(section.get("title") or ""),
					text=_strip_nul(str(section.get("text") or "")),
					start_offset=int(section.get("start_offset") or 0),
					end_offset=int(section.get("end_offset") or 0),
					content_sha256=sha256_hex(str(section.get("text") or "").encode("utf-8")),
				)
			)

		version.extracted_blob_container = extracted_container
		version.extracted_blob_name = extracted_blob_path
		version.extracted_blob_uri = extracted_uri

		version.parse_status = ParseStatus.READY
		version.parse_status_updated_at = datetime.now(timezone.utc)

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
	except Exception as exc:
		logger.exception(
			"worker.persistence_failed",
			extra={"policy_version_id": str(policy_version_id), "correlation_id": correlation_id},
		)
		db.rollback()
		try:
			_mark_policy_version_failed(
				db=db,
				version=version,
				error_code="persist_failed",
				error_message=str(exc),
			)
		except SQLAlchemyError:
			db.rollback()
		return


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
