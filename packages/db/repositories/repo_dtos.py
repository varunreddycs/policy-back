"""Portable data transfer objects for the repository layer.

These dataclasses are the lingua franca between repository implementations
and business services. They carry no ORM coupling — just stdlib types.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class PolicyDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    external_id: str
    name: str
    status: str
    jurisdiction: Optional[str] = None
    category: Optional[str] = None
    authority_level: int = 0
    department_scope: str = "all"
    policy_type: Optional[str] = None
    current_version_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    created_by_user_id: Optional[uuid.UUID] = None
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[uuid.UUID] = None


@dataclass(frozen=True, slots=True)
class PolicyVersionDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    policy_id: uuid.UUID
    version_number: int
    content_sha256: str
    metadata_sha256: str
    blob_container: str
    blob_name: str
    parse_status: str
    is_current: bool = False
    version_label: Optional[str] = None
    supersedes_policy_version_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    effective_date: Optional[date] = None
    blob_version_id: Optional[str] = None
    blob_etag: Optional[str] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    extracted_blob_container: Optional[str] = None
    extracted_blob_name: Optional[str] = None
    extracted_blob_uri: Optional[str] = None
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    ingest_batch_id: Optional[uuid.UUID] = None
    parse_status_updated_at: Optional[datetime] = None
    parse_error_code: Optional[str] = None
    parse_error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_user_id: Optional[uuid.UUID] = None
    correlation_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PolicySectionDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    policy_version_id: uuid.UUID
    section_index: int
    text: str
    content_sha256: str
    section_path: Optional[str] = None
    title: Optional[str] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    rag_document_id: Optional[str] = None
    rag_node_id: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class SectionDetailDTO:
    """Enriched section with parent policy/version metadata — used by the detail endpoint."""
    section_id: uuid.UUID
    tenant_id: uuid.UUID
    policy_id: uuid.UUID
    policy_version_id: uuid.UUID
    policy_name: str
    section_index: int
    section_path: Optional[str]
    section_title: Optional[str]
    text: str
    effective_date: Optional[date]
    is_current: bool
    public_url: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    policy_version_id: uuid.UUID
    policy_section_id: uuid.UUID
    embedding_model: str
    embedding: Any  # list[float] or binary depending on backend
    content_sha256: Optional[str] = None
    authority_level: Optional[int] = None
    department_scope: Optional[str] = None
    policy_type: Optional[str] = None
    effective_date: Optional[date] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class AuditLogDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class IngestBatchDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    submitted_by_user_id: Optional[uuid.UUID] = None
    source_system: Optional[str] = None
    status_reason: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class IngestItemDTO:
    id: uuid.UUID
    tenant_id: uuid.UUID
    batch_id: uuid.UUID
    status: str
    policy_id: Optional[uuid.UUID] = None
    blob_container: Optional[str] = None
    blob_name: Optional[str] = None
    content_sha256: Optional[str] = None
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    metadata_sha256: Optional[str] = None
    correlation_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_policy_version_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class PolicyReferenceDTO:
    id: uuid.UUID
    reference_type: str
    resolution_status: str
    matched_text: str
    confidence: float
    extractor_version: str
    source_section_id: uuid.UUID
    source_policy_version_id: uuid.UUID
    target_section_id: Optional[uuid.UUID] = None
    target_policy_id: Optional[uuid.UUID] = None
    target_section_title: Optional[str] = None
    target_section_path: Optional[str] = None
    target_policy_name: Optional[str] = None
    target_external_uri: Optional[str] = None
    target_external_label: Optional[str] = None
    match_offset: Optional[int] = None
    created_at: Optional[datetime] = None
