from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field

from deps import get_blob_service, get_ingestion_service
from models.policy_models import IngestionBatchCreateRequest, IngestionBatchResponse
from services import BlobNotFoundError, BlobService, BlobServiceError
from services.ingestion_service import (
	ConflictError,
	DuplicateVersionError,
	IngestionService,
	NotFoundError,
	PublishError,
	VersionLabelConflictError,
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
	version_label: Optional[str] = Field(default=None, max_length=128, description="Optional client version label (unique per policy)")
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

