from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.db.models.policy_models import (
    IngestBatch,
    IngestItem,
    Policy,
    PolicyVersion,
    metadata_sha256,
    sha256_hex,
)
from packages.db.repositories.ingestion_repositories import (
    IngestBatchRepository,
    IngestItemRepository,
    PolicyRepository,
    PolicyVersionRepository,
)
from packages.queue.queue_service import QueueService
from packages.storage.blob_service import BlobService


logger = logging.getLogger(__name__)


class IngestionDomainError(RuntimeError):
    pass


class NotFoundError(IngestionDomainError):
    pass


class ConflictError(IngestionDomainError):
    pass


class DuplicateVersionError(ConflictError):
    def __init__(self, message: str, *, existing_policy_version_id: uuid.UUID) -> None:
        super().__init__(message)
        self.existing_policy_version_id = existing_policy_version_id


class VersionLabelConflictError(ConflictError):
    def __init__(self, message: str, *, policy_id: uuid.UUID, version_label: str) -> None:
        super().__init__(message)
        self.policy_id = policy_id
        self.version_label = version_label


def _integrity_constraint_name(exc: IntegrityError) -> Optional[str]:
    orig = getattr(exc, "orig", None)
    if orig is not None:
        diag = getattr(orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
        if name:
            return str(name)
        msg = str(orig)
        if "uq_policy_versions_policy_id_version_label" in msg:
            return "uq_policy_versions_policy_id_version_label"
    return None


class PublishError(IngestionDomainError):
    pass


@dataclass(frozen=True, slots=True)
class IngestBatchDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    submitted_by_user_id: Optional[uuid.UUID]
    source_system: Optional[str]
    status: str
    status_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    correlation_id: Optional[str]


@dataclass(frozen=True, slots=True)
class UploadUrlDTO:
    upload_sas_url: str
    blob_uri: str
    expires_in_minutes: int


@dataclass(frozen=True, slots=True)
class RegisteredDocumentDTO:
    ingest_item_id: uuid.UUID
    policy_id: uuid.UUID
    policy_version_id: uuid.UUID
    version_number: int
    content_sha256: str
    metadata_sha256: str
    parse_status: str


class IngestionService:
    """Business service for policy ingestion."""

    def __init__(
        self,
        *,
        session: Session,
        blob_service: BlobService,
        queue_service: QueueService,
    ) -> None:
        self._session = session
        self._blob_service = blob_service
        self._queue_service = queue_service

        self._policies = PolicyRepository(session)
        self._versions = PolicyVersionRepository(session)
        self._batches = IngestBatchRepository(session)
        self._items = IngestItemRepository(session)

    def create_ingestion_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        submitted_by_user_id: Optional[uuid.UUID] = None,
        source_system: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> IngestBatchDTO:
        with self._session.begin():
            batch = IngestBatch(
                tenant_id=tenant_id,
                submitted_by_user_id=submitted_by_user_id,
                source_system=source_system,
                correlation_id=correlation_id,
                status="received",
            )
            self._batches.add(batch)
            self._session.flush()
            self._session.refresh(batch)

            logger.info(
                "ingestion.batch_created",
                extra={
                    "tenant_id": str(tenant_id),
                    "batch_id": str(batch.id),
                    "status": batch.status,
                    "correlation_id": correlation_id,
                },
            )

            return IngestBatchDTO(
                id=batch.id,
                tenant_id=batch.tenant_id,
                submitted_by_user_id=batch.submitted_by_user_id,
                source_system=batch.source_system,
                status=batch.status,
                status_reason=batch.status_reason,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
                correlation_id=batch.correlation_id,
            )

    def get_ingestion_batch(self, *, tenant_id: uuid.UUID, batch_id: uuid.UUID) -> IngestBatchDTO:
        batch = self._batches.get(batch_id)
        if batch is None or batch.tenant_id != tenant_id:
            raise NotFoundError("Ingestion batch not found")
        return IngestBatchDTO(
            id=batch.id,
            tenant_id=batch.tenant_id,
            submitted_by_user_id=batch.submitted_by_user_id,
            source_system=batch.source_system,
            status=batch.status,
            status_reason=batch.status_reason,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
            correlation_id=batch.correlation_id,
        )

    def generate_upload_url(
        self,
        *,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID,
        container_name: str,
        blob_path: str,
        expires_in_minutes: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> UploadUrlDTO:
        _ = self.get_ingestion_batch(tenant_id=tenant_id, batch_id=batch_id)

        minutes = expires_in_minutes or 15
        upload_url = self._blob_service.generate_upload_sas_url(
            container_name,
            blob_path,
            expires_in_minutes=minutes,
            content_type=content_type,
        )
        blob_uri = self._blob_service.get_blob_uri(container_name, blob_path)

        logger.info(
            "ingestion.upload_url_generated",
            extra={
                "tenant_id": str(tenant_id),
                "batch_id": str(batch_id),
                "container": container_name,
                "blob": blob_path,
                "expires_in_minutes": minutes,
            },
        )
        return UploadUrlDTO(upload_sas_url=upload_url, blob_uri=blob_uri, expires_in_minutes=minutes)

    def register_uploaded_document(
        self,
        *,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID,
        container_name: str,
        blob_path: str,
        policy_external_id: str,
        policy_name: str,
        version_label: Optional[str],
        metadata: Dict[str, Any],
        submitted_by_user_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[str] = None,
        blob_version_id: Optional[str] = None,
        blob_etag: Optional[str] = None,
        content_type: Optional[str] = None,
        content_length: Optional[int] = None,
        effective_date: Optional[date] = None,
        title: Optional[str] = None,
    ) -> RegisteredDocumentDTO:
        if not policy_external_id or not policy_external_id.strip():
            raise ValueError("policy_external_id must be non-empty")
        if not policy_name or not policy_name.strip():
            raise ValueError("policy_name must be non-empty")

        blob_bytes = self._blob_service.download_blob_bytes(container_name, blob_path)
        content_hash = sha256_hex(blob_bytes)
        metadata_hash = metadata_sha256(metadata)

        with self._session.begin():
            batch = self._batches.get(batch_id)
            if batch is None or batch.tenant_id != tenant_id:
                raise NotFoundError("Ingestion batch not found")

            policy = self._policies.get_by_external_id(tenant_id=tenant_id, external_id=policy_external_id)
            if policy is None:
                policy = Policy(
                    tenant_id=tenant_id,
                    external_id=policy_external_id,
                    name=policy_name,
                    status="draft",
                    created_by_user_id=submitted_by_user_id,
                    updated_by_user_id=submitted_by_user_id,
                )
                self._policies.add(policy)
                self._session.flush()
                logger.info(
                    "ingestion.policy_created",
                    extra={
                        "tenant_id": str(tenant_id),
                        "policy_id": str(policy.id),
                        "external_id": policy_external_id,
                    },
                )

            # Phase 2: persist stable policy metadata onto the policy row so retrieval filters work.
            # Keep this conservative: only set fields when metadata provides a value.
            policy_type = metadata.get("policy_type") or metadata.get("type")
            if policy_type and not getattr(policy, "policy_type", None):
                policy.policy_type = str(policy_type)

            department_scope = metadata.get("department_scope") or metadata.get("department")
            if department_scope and (getattr(policy, "department_scope", None) in (None, "", "all")):
                policy.department_scope = str(department_scope)

            authority_level = metadata.get("authority_level")
            if authority_level is not None:
                try:
                    authority_level_int = int(authority_level)
                    if authority_level_int >= 0 and int(getattr(policy, "authority_level", 0) or 0) == 0:
                        policy.authority_level = authority_level_int
                except Exception:
                    pass

            existing_id = self._versions.exists_duplicate(
                policy_id=policy.id,
                content_sha256=content_hash,
                metadata_sha256=metadata_hash,
            )
            if existing_id:
                logger.info(
                    "ingestion.duplicate_detected",
                    extra={
                        "tenant_id": str(tenant_id),
                        "policy_id": str(policy.id),
                        "existing_policy_version_id": str(existing_id),
                        "content_sha256": content_hash,
                        "metadata_sha256": metadata_hash,
                    },
                )
                raise DuplicateVersionError(
                    "Duplicate policy version detected (content+metadata match)",
                    existing_policy_version_id=existing_id,
                )

            version_number = self._versions.next_version_number(policy_id=policy.id)

            supersedes_id: Optional[uuid.UUID] = None
            if version_number > 1:
                supersedes_id = self._versions.latest_version_id(policy_id=policy.id)

            policy_id = policy.id
            policy_version = PolicyVersion(
                tenant_id=tenant_id,
                policy_id=policy_id,
                version_number=version_number,
                version_label=version_label,
                supersedes_policy_version_id=supersedes_id,
                title=title,
                effective_date=effective_date,
                blob_container=container_name,
                blob_name=blob_path,
                blob_version_id=blob_version_id,
                blob_etag=blob_etag,
                content_type=content_type,
                content_length=content_length,
                content_sha256=content_hash,
                metadata_json=metadata,
                metadata_sha256=metadata_hash,
                ingest_batch_id=batch.id,
                parse_status="pending",
                parse_status_updated_at=datetime.now(UTC),
                correlation_id=correlation_id,
                created_by_user_id=submitted_by_user_id,
            )
            self._versions.add(policy_version)

            ingest_item = IngestItem(
                tenant_id=tenant_id,
                batch_id=batch.id,
                policy_id=policy_id,
                blob_container=container_name,
                blob_name=blob_path,
                blob_version_id=blob_version_id,
                blob_etag=blob_etag,
                content_type=content_type,
                content_length=content_length,
                content_sha256=content_hash,
                metadata_json=metadata,
                metadata_sha256=metadata_hash,
                correlation_id=correlation_id,
                status="received",
                result_policy_version_id=None,
            )
            self._items.add(ingest_item)

            try:
                self._session.flush()
            except IntegrityError as exc:
                constraint_name = _integrity_constraint_name(exc)
                logger.exception(
                    "ingestion.db_integrity_error",
                    extra={
                        "tenant_id": str(tenant_id),
                        "policy_id": str(policy_id),
                        "constraint": constraint_name,
                        "content_sha256": content_hash,
                        "metadata_sha256": metadata_hash,
                    },
                )
                if (
                    constraint_name == "uq_policy_versions_policy_id_version_label"
                    and version_label is not None
                    and version_label.strip()
                ):
                    raise VersionLabelConflictError(
                        "version_label already exists for this policy",
                        policy_id=policy_id,
                        version_label=version_label,
                    ) from exc
                raise ConflictError("Conflict while creating policy version") from exc

            ingest_item.result_policy_version_id = policy_version.id

            logger.info(
                "ingestion.document_registered",
                extra={
                    "tenant_id": str(tenant_id),
                    "batch_id": str(batch.id),
                    "ingest_item_id": str(ingest_item.id),
                    "policy_id": str(policy.id),
                    "policy_version_id": str(policy_version.id),
                    "version_number": version_number,
                    "parse_status": policy_version.parse_status,
                },
            )

            dto = RegisteredDocumentDTO(
                ingest_item_id=ingest_item.id,
                policy_id=policy_id,
                policy_version_id=policy_version.id,
                version_number=version_number,
                content_sha256=content_hash,
                metadata_sha256=metadata_hash,
                parse_status=policy_version.parse_status,
            )

        try:
            self._queue_service.enqueue_policy_processing(dto.policy_version_id, correlation_id=correlation_id)
        except Exception as exc:
            logger.exception(
                "ingestion.queue_publish_failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "batch_id": str(batch_id),
                    "ingest_item_id": str(dto.ingest_item_id),
                    "policy_version_id": str(dto.policy_version_id),
                },
            )
            with self._session.begin():
                self._items.set_status(
                    item_id=dto.ingest_item_id,
                    status="failed",
                    error_code="QUEUE_PUBLISH_FAILED",
                    error_message=str(exc),
                )
            raise PublishError("Failed to publish extraction request") from exc

        with self._session.begin():
            self._items.set_status(item_id=dto.ingest_item_id, status="queued")
            batch = self._batches.get(batch_id)
            if batch is not None and batch.tenant_id == tenant_id and batch.status == "received":
                batch.status = "queued"

        return dto


__all__ = [
    "IngestionService",
    "DuplicateVersionError",
    "VersionLabelConflictError",
    "ConflictError",
    "NotFoundError",
    "PublishError",
]
