from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from datetime import date
from html import unescape
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.deps import get_blob_service, get_ingestion_service
from packages.db.models.policy_models import IngestionBatchCreateRequest, IngestionBatchResponse
from packages.extraction.extractor import extract_sections
from packages.ingestion.ingestion_service import (
	ConflictError,
	DuplicateVersionError,
	IngestionService,
	NotFoundError,
	PublishError,
	VersionLabelConflictError,
)
from packages.storage.blob_service import (
	BlobNotFoundError,
	BlobService,
	BlobServiceError,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ingest", tags=["Ingestion"])


class UploadUrlRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	container_name: str = Field(min_length=1, max_length=128, description="Azure Blob container")
	blob_path: str = Field(min_length=1, max_length=1024, description="Blob path/name")
	expires_in_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
	content_type: Optional[str] = Field(default=None, max_length=128)


class UploadUrlResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	upload_sas_url: str
	blob_uri: str
	expires_in_minutes: int


class RegisterDocumentRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	container_name: str = Field(min_length=1, max_length=128)
	blob_path: str = Field(min_length=1, max_length=1024)
	policy_external_id: str = Field(min_length=1, max_length=128)
	policy_name: str = Field(min_length=1, max_length=512)
	version_label: Optional[str] = Field(
		default=None,
		max_length=128,
		description="Optional client version label (unique per policy)",
	)
	metadata: Dict[str, Any] = Field(default_factory=dict)

	submitted_by_user_id: Optional[uuid.UUID] = None
	correlation_id: Optional[str] = Field(default=None, max_length=128)

	blob_version_id: Optional[str] = Field(default=None, max_length=256)
	blob_etag: Optional[str] = Field(default=None, max_length=128)
	content_type: Optional[str] = Field(default=None, max_length=128)
	content_length: Optional[int] = Field(default=None, ge=0)

	effective_date: Optional[date] = None
	title: Optional[str] = Field(default=None, max_length=512)


class RegisterDocumentResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	ingest_item_id: uuid.UUID
	policy_id: uuid.UUID
	policy_version_id: uuid.UUID
	version_number: int
	content_sha256: str
	metadata_sha256: str
	parse_status: str


class CrawlUrlRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	url: str = Field(min_length=1, max_length=2048)
	container_name: str = Field(min_length=1, max_length=128)
	policy_external_id: str = Field(min_length=1, max_length=128)
	policy_name: str = Field(min_length=1, max_length=512)
	version_label: Optional[str] = Field(default=None, max_length=128)
	blob_path: Optional[str] = Field(default=None, max_length=1024)
	metadata: Dict[str, Any] = Field(default_factory=dict)
	correlation_id: Optional[str] = Field(default=None, max_length=128)
	title: Optional[str] = Field(default=None, max_length=512)


def _guess_extension_from_content_type(content_type: str) -> str:
	ct = (content_type or "").lower()
	if "pdf" in ct:
		return ".pdf"
	if "wordprocessingml" in ct or "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in ct:
		return ".docx"
	if "html" in ct:
		return ".html"
	if "markdown" in ct:
		return ".md"
	if "text/plain" in ct:
		return ".txt"
	return ".bin"


def _clean_html_to_text(raw_html: str) -> str:
	# Minimal HTML cleanup without external dependencies.
	text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", raw_html)
	text = re.sub(r"(?i)<br\\s*/?>", "\\n", text)
	text = re.sub(r"(?i)</p\\s*>", "\\n\\n", text)
	text = re.sub(r"<[^>]+>", " ", text)
	text = unescape(text)
	text = re.sub(r"\\r", "", text)
	text = re.sub(r"\\n{3,}", "\\n\\n", text)
	text = re.sub(r"[ \\t]{2,}", " ", text)
	return text.strip()


def _map_domain_exception(exc: Exception) -> HTTPException:
	if isinstance(exc, DuplicateVersionError):
		return HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail={
				"code": "DUPLICATE_VERSION",
				"message": str(exc),
				"existing_policy_version_id": str(exc.existing_policy_version_id),
			},
		)
	if isinstance(exc, VersionLabelConflictError):
		return HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail={
				"code": "VERSION_LABEL_CONFLICT",
				"message": str(exc),
				"policy_id": str(exc.policy_id),
				"version_label": exc.version_label,
			},
		)
	if isinstance(exc, ConflictError):
		return HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail={"code": "CONFLICT", "message": str(exc)},
		)
	if isinstance(exc, NotFoundError):
		return HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"code": "NOT_FOUND", "message": str(exc)},
		)
	if isinstance(exc, (BlobNotFoundError,)):
		return HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"code": "BLOB_NOT_FOUND", "message": str(exc)},
		)
	if isinstance(exc, (PublishError, BlobServiceError)):
		return HTTPException(
			status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
			detail={"code": "DEPENDENCY_FAILURE", "message": str(exc)},
		)
	return HTTPException(
		status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
		detail={"code": "INTERNAL_ERROR", "message": "Unexpected error"},
	)


@router.post(
	"/batches",
	response_model=IngestionBatchResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Create ingestion batch",
	description="Creates an ingestion batch to group uploaded policy documents.",
)
def create_batch(
	request: IngestionBatchCreateRequest,
	service: IngestionService = Depends(get_ingestion_service),
) -> IngestionBatchResponse:
	try:
		dto = service.create_ingestion_batch(
			tenant_id=request.tenant_id,
			submitted_by_user_id=request.submitted_by_user_id,
			source_system=request.source_system,
			correlation_id=request.correlation_id,
		)
		return IngestionBatchResponse(
			id=dto.id,
			tenant_id=dto.tenant_id,
			submitted_by_user_id=dto.submitted_by_user_id,
			source_system=dto.source_system,
			status=dto.status,
			status_reason=dto.status_reason,
			correlation_id=dto.correlation_id,
			created_at=dto.created_at,
			updated_at=dto.updated_at,
		)
	except Exception as exc:
		logger.exception("api.ingest.create_batch_failed")
		raise _map_domain_exception(exc)


@router.get(
	"/batches/{batch_id}",
	response_model=IngestionBatchResponse,
	summary="Get ingestion batch",
	description="Fetches an ingestion batch (tenant-scoped).",
)
def get_batch(
	batch_id: uuid.UUID = Path(..., description="Batch UUID"),
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	service: IngestionService = Depends(get_ingestion_service),
) -> IngestionBatchResponse:
	try:
		dto = service.get_ingestion_batch(tenant_id=tenant_id, batch_id=batch_id)
		return IngestionBatchResponse(
			id=dto.id,
			tenant_id=dto.tenant_id,
			submitted_by_user_id=dto.submitted_by_user_id,
			source_system=dto.source_system,
			status=dto.status,
			status_reason=dto.status_reason,
			correlation_id=dto.correlation_id,
			created_at=dto.created_at,
			updated_at=dto.updated_at,
		)
	except Exception as exc:
		logger.exception("api.ingest.get_batch_failed", extra={"batch_id": str(batch_id)})
		raise _map_domain_exception(exc)


@router.post(
	"/batches/{batch_id}/upload-urls",
	response_model=UploadUrlResponse,
	summary="Generate upload SAS URL",
	description="Generates a time-limited SAS URL for client upload to Azure Blob Storage.",
)
def generate_upload_url(
	request: UploadUrlRequest,
	batch_id: uuid.UUID = Path(..., description="Batch UUID"),
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	service: IngestionService = Depends(get_ingestion_service),
) -> UploadUrlResponse:
	try:
		dto = service.generate_upload_url(
			tenant_id=tenant_id,
			batch_id=batch_id,
			container_name=request.container_name,
			blob_path=request.blob_path,
			expires_in_minutes=request.expires_in_minutes,
			content_type=request.content_type,
		)
		return UploadUrlResponse(
			upload_sas_url=dto.upload_sas_url,
			blob_uri=dto.blob_uri,
			expires_in_minutes=dto.expires_in_minutes,
		)
	except Exception as exc:
		logger.exception(
			"api.ingest.generate_upload_url_failed",
			extra={"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
		)
		raise _map_domain_exception(exc)


@router.post(
	"/batches/{batch_id}/register",
	response_model=RegisterDocumentResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Register uploaded policy document",
	description=(
		"Registers a previously-uploaded blob as an ingestion item and creates an immutable policy version. "
		"Also enqueues background extraction via Azure Storage Queue."
	),
)
def register_uploaded_document(
	request: RegisterDocumentRequest,
	batch_id: uuid.UUID = Path(..., description="Batch UUID"),
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	service: IngestionService = Depends(get_ingestion_service),
) -> RegisterDocumentResponse:
	try:
		dto = service.register_uploaded_document(
			tenant_id=tenant_id,
			batch_id=batch_id,
			container_name=request.container_name,
			blob_path=request.blob_path,
			policy_external_id=request.policy_external_id,
			policy_name=request.policy_name,
			version_label=request.version_label,
			metadata=request.metadata,
			submitted_by_user_id=request.submitted_by_user_id,
			correlation_id=request.correlation_id,
			blob_version_id=request.blob_version_id,
			blob_etag=request.blob_etag,
			content_type=request.content_type,
			content_length=request.content_length,
			effective_date=request.effective_date,
			title=request.title,
		)
		return RegisterDocumentResponse(
			ingest_item_id=dto.ingest_item_id,
			policy_id=dto.policy_id,
			policy_version_id=dto.policy_version_id,
			version_number=dto.version_number,
			content_sha256=dto.content_sha256,
			metadata_sha256=dto.metadata_sha256,
			parse_status=dto.parse_status,
		)
	except Exception as exc:
		logger.exception(
			"api.ingest.register_failed",
			extra={"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
		)
		raise _map_domain_exception(exc)


@router.post(
	"/batches/{batch_id}/upload-and-register",
	response_model=RegisterDocumentResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Upload file, parse, and register",
	description=(
		"Uploads a file through API, validates parser support before upload, then registers it "
		"for ingestion and queue processing."
	),
)
async def upload_and_register_document(
	batch_id: uuid.UUID = Path(..., description="Batch UUID"),
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	file: UploadFile = File(...),
	container_name: str = Form(...),
	policy_external_id: str = Form(...),
	policy_name: str = Form(...),
	version_label: Optional[str] = Form(default=None),
	blob_path: Optional[str] = Form(default=None),
	metadata_json: Optional[str] = Form(default=None),
	correlation_id: Optional[str] = Form(default=None),
	title: Optional[str] = Form(default=None),
	service: IngestionService = Depends(get_ingestion_service),
	blob_service: BlobService = Depends(get_blob_service),
) -> RegisterDocumentResponse:
	try:
		file_bytes = await file.read()
		if not file_bytes:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail={"code": "EMPTY_FILE", "message": "Uploaded file is empty"},
			)

		# Parse first to enforce parser-based ingestion instead of notebook pre-processing.
		extract_sections(filename=file.filename or "uploaded.bin", content_bytes=file_bytes)

		metadata: Dict[str, Any] = {}
		if metadata_json:
			import json

			metadata = json.loads(metadata_json)
		metadata.setdefault("upload_channel", "api-upload")
		metadata.setdefault("original_filename", file.filename or "uploaded.bin")

		final_blob_path = blob_path
		if not final_blob_path:
			timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
			clean_name = (file.filename or "uploaded.bin").replace(" ", "-")
			final_blob_path = f"uploads/{tenant_id}/{timestamp}-{uuid.uuid4().hex[:8]}-{clean_name}"

		blob_service.upload_blob_bytes(
			container_name,
			final_blob_path,
			file_bytes,
			content_type=file.content_type or "application/octet-stream",
			overwrite=True,
		)

		dto = service.register_uploaded_document(
			tenant_id=tenant_id,
			batch_id=batch_id,
			container_name=container_name,
			blob_path=final_blob_path,
			policy_external_id=policy_external_id,
			policy_name=policy_name,
			version_label=version_label,
			metadata=metadata,
			correlation_id=correlation_id,
			content_type=file.content_type,
			content_length=len(file_bytes),
			title=title,
		)

		return RegisterDocumentResponse(
			ingest_item_id=dto.ingest_item_id,
			policy_id=dto.policy_id,
			policy_version_id=dto.policy_version_id,
			version_number=dto.version_number,
			content_sha256=dto.content_sha256,
			metadata_sha256=dto.metadata_sha256,
			parse_status=dto.parse_status,
		)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception(
			"api.ingest.upload_and_register_failed",
			extra={"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
		)
		raise _map_domain_exception(exc)


@router.post(
	"/batches/{batch_id}/crawl-and-register",
	response_model=RegisterDocumentResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Crawl URL, parse, and register",
	description=(
		"Downloads content from a URL, validates parser support, uploads to blob storage, "
		"and registers the document into ingestion pipeline."
	),
)
def crawl_and_register_document(
	request: CrawlUrlRequest,
	batch_id: uuid.UUID = Path(..., description="Batch UUID"),
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	service: IngestionService = Depends(get_ingestion_service),
	blob_service: BlobService = Depends(get_blob_service),
) -> RegisterDocumentResponse:
	try:
		parsed = urlparse(request.url)
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail={"code": "INVALID_URL", "message": "Only http/https URLs are supported"},
			)

		req = Request(
			request.url,
			headers={
				"User-Agent": (
					"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
					"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
				)
			},
		)
		with urlopen(req, timeout=60) as response:
			source_bytes = response.read()
			content_type = response.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()

		if not source_bytes:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail={"code": "EMPTY_SOURCE", "message": "Fetched URL returned no content"},
			)

		path_name = (urlparse(request.url).path or "").rstrip("/")
		base_name = path_name.split("/")[-1] if path_name else "document"
		if "." in base_name:
			filename = base_name
		else:
			ext = _guess_extension_from_content_type(content_type)
			filename = f"{base_name}{ext}"

		parse_bytes = source_bytes
		parse_filename = filename
		upload_content_type = content_type

		if filename.lower().endswith((".html", ".htm")) or "html" in content_type.lower():
			html_text = source_bytes.decode("utf-8", errors="replace")
			clean_text = _clean_html_to_text(html_text)
			parse_bytes = clean_text.encode("utf-8")
			parse_filename = re.sub(r"\\.(html|htm)$", ".txt", filename, flags=re.IGNORECASE)
			upload_content_type = "text/plain"

		# Parse first to keep URL flow aligned with parser-first ingestion.
		extract_sections(filename=parse_filename, content_bytes=parse_bytes)

		blob_path = request.blob_path
		if not blob_path:
			timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
			clean_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", parse_filename)
			blob_path = f"crawled/{tenant_id}/{timestamp}-{uuid.uuid4().hex[:8]}-{clean_name}"

		blob_service.upload_blob_bytes(
			request.container_name,
			blob_path,
			parse_bytes,
			content_type=upload_content_type,
			overwrite=True,
		)

		metadata = dict(request.metadata or {})
		metadata.setdefault("upload_channel", "url-crawl")
		metadata.setdefault("source_url", request.url)
		metadata.setdefault("public_url", request.url)
		metadata.setdefault("original_content_type", content_type)
		metadata.setdefault("original_filename", filename)

		dto = service.register_uploaded_document(
			tenant_id=tenant_id,
			batch_id=batch_id,
			container_name=request.container_name,
			blob_path=blob_path,
			policy_external_id=request.policy_external_id,
			policy_name=request.policy_name,
			version_label=request.version_label,
			metadata=metadata,
			correlation_id=request.correlation_id,
			content_type=upload_content_type,
			content_length=len(parse_bytes),
			title=request.title,
		)

		return RegisterDocumentResponse(
			ingest_item_id=dto.ingest_item_id,
			policy_id=dto.policy_id,
			policy_version_id=dto.policy_version_id,
			version_number=dto.version_number,
			content_sha256=dto.content_sha256,
			metadata_sha256=dto.metadata_sha256,
			parse_status=dto.parse_status,
		)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception(
			"api.ingest.crawl_and_register_failed",
			extra={"batch_id": str(batch_id), "tenant_id": str(tenant_id), "url": request.url},
		)
		raise _map_domain_exception(exc)


__all__ = ["router"]
