"""Repository interfaces (ABCs) for database-agnostic data access.

All methods accept/return stdlib types, UUIDs, datetimes, and DTOs from
`packages.db.repositories.repo_dtos` — never ORM models. This allows
swapping the backing store (PostgreSQL, Cosmos DB NoSQL, etc.) via the
factory without touching business logic.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from packages.db.repositories.repo_dtos import (
    AuditLogDTO,
    EmbeddingDTO,
    IngestBatchDTO,
    IngestItemDTO,
    PolicyDTO,
    PolicyReferenceDTO,
    PolicySectionDTO,
    PolicyVersionDTO,
    SectionDetailDTO,
)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class IPolicyRepository(ABC):
    @abstractmethod
    def get_by_id(self, *, policy_id: uuid.UUID) -> Optional[PolicyDTO]:
        ...

    @abstractmethod
    def get_by_external_id(self, *, tenant_id: uuid.UUID, external_id: str) -> Optional[PolicyDTO]:
        ...

    @abstractmethod
    def list_for_tenant(self, *, tenant_id: uuid.UUID) -> List[PolicyDTO]:
        ...

    @abstractmethod
    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        external_id: str,
        name: str,
        status: str = "draft",
        jurisdiction: Optional[str] = None,
        category: Optional[str] = None,
        authority_level: int = 0,
        department_scope: str = "all",
        policy_type: Optional[str] = None,
        created_by_user_id: Optional[uuid.UUID] = None,
    ) -> PolicyDTO:
        ...

    @abstractmethod
    def update(
        self,
        *,
        policy_id: uuid.UUID,
        current_version_id: Optional[uuid.UUID] = ...,
        policy_type: Optional[str] = ...,
        department_scope: Optional[str] = ...,
        authority_level: Optional[int] = ...,
        updated_by_user_id: Optional[uuid.UUID] = ...,
    ) -> Optional[PolicyDTO]:
        ...


# ---------------------------------------------------------------------------
# Policy Version
# ---------------------------------------------------------------------------


class IPolicyVersionRepository(ABC):
    @abstractmethod
    def get_by_id(self, *, version_id: uuid.UUID) -> Optional[PolicyVersionDTO]:
        ...

    @abstractmethod
    def list_for_policy(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> List[PolicyVersionDTO]:
        ...

    @abstractmethod
    def exists_duplicate(
        self, *, policy_id: uuid.UUID, content_sha256: str, metadata_sha256: str
    ) -> Optional[uuid.UUID]:
        ...

    @abstractmethod
    def next_version_number(self, *, policy_id: uuid.UUID) -> int:
        ...

    @abstractmethod
    def latest_version_id(self, *, policy_id: uuid.UUID) -> Optional[uuid.UUID]:
        ...

    @abstractmethod
    def create(self, **fields: Any) -> PolicyVersionDTO:
        ...

    @abstractmethod
    def set_parse_status(
        self,
        *,
        version_id: uuid.UUID,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    @abstractmethod
    def set_current(self, *, policy_id: uuid.UUID, version_id: uuid.UUID) -> None:
        """Mark *version_id* as is_current and clear the flag on all other versions of the same policy."""
        ...

    @abstractmethod
    def set_extracted_blob(
        self,
        *,
        version_id: uuid.UUID,
        extracted_blob_container: str,
        extracted_blob_name: str,
        extracted_blob_uri: str,
    ) -> None:
        ...


# ---------------------------------------------------------------------------
# Policy Section
# ---------------------------------------------------------------------------


class IPolicySectionRepository(ABC):
    @abstractmethod
    def list_for_version(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_version_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> List[PolicySectionDTO]:
        ...

    @abstractmethod
    def get_detail(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> Optional[SectionDetailDTO]:
        ...

    @abstractmethod
    def bulk_insert(self, sections: List[Dict[str, Any]]) -> int:
        """Insert a batch of section dicts. Returns count inserted."""
        ...

    @abstractmethod
    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        ...

    @abstractmethod
    def exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        ...


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class IEmbeddingRepository(ABC):
    @abstractmethod
    def bulk_insert(self, embeddings: List[Dict[str, Any]]) -> int:
        ...

    @abstractmethod
    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        ...


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class IAuditRepository(ABC):
    @abstractmethod
    def write(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        correlation_id: Optional[str],
        payload: Dict[str, Any],
    ) -> uuid.UUID:
        ...

    @abstractmethod
    def get_by_id(self, *, audit_id: uuid.UUID) -> Optional[AuditLogDTO]:
        ...

    @abstractmethod
    def list_for_tenant(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> List[AuditLogDTO]:
        ...


# ---------------------------------------------------------------------------
# Ingest Batch
# ---------------------------------------------------------------------------


class IIngestBatchRepository(ABC):
    @abstractmethod
    def get(self, batch_id: uuid.UUID) -> Optional[IngestBatchDTO]:
        ...

    @abstractmethod
    def create(self, **fields: Any) -> IngestBatchDTO:
        ...

    @abstractmethod
    def update_status(self, *, batch_id: uuid.UUID, status: str) -> None:
        ...


# ---------------------------------------------------------------------------
# Ingest Item
# ---------------------------------------------------------------------------


class IIngestItemRepository(ABC):
    @abstractmethod
    def create(self, **fields: Any) -> IngestItemDTO:
        ...

    @abstractmethod
    def set_status(
        self,
        *,
        item_id: uuid.UUID,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result_policy_version_id: Optional[uuid.UUID] = None,
    ) -> None:
        ...

    @abstractmethod
    def count_active_for_batch(self, *, batch_id: uuid.UUID) -> int:
        """Count items still in a non-terminal state (received/queued/processing)."""
        ...


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


class IReferenceRepository(ABC):
    @abstractmethod
    def bulk_insert(self, refs: List[Dict[str, Any]]) -> int:
        ...

    @abstractmethod
    def delete_for_section(self, *, section_id: uuid.UUID) -> int:
        ...

    @abstractmethod
    def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
        ...

    @abstractmethod
    def list_outbound_for_section(
        self, *, tenant_id: uuid.UUID, section_id: uuid.UUID
    ) -> List[PolicyReferenceDTO]:
        ...

    @abstractmethod
    def list_inbound_for_section(
        self, *, tenant_id: uuid.UUID, section_id: uuid.UUID
    ) -> List[PolicyReferenceDTO]:
        ...

    @abstractmethod
    def list_for_policy_version(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_version_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[PolicyReferenceDTO]:
        ...

    @abstractmethod
    def section_exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        ...

    @abstractmethod
    def policy_version_exists_for_tenant(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID) -> bool:
        ...
