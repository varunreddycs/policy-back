from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import (
	Boolean,
	CheckConstraint,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	MetaData,
	String,
	Text,
	UniqueConstraint,
	func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


NAMING_CONVENTION = {
	"ix": "ix_%(column_0_label)s",
	"uq": "uq_%(table_name)s_%(column_0_name)s",
	"ck": "ck_%(table_name)s_%(constraint_name)s",
	"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
	"pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
	metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PolicyStatus(str, Enum):
	DRAFT = "draft"
	ACTIVE = "active"
	RETIRED = "retired"


class IngestionBatchStatus(str, Enum):
	RECEIVED = "received"
	QUEUED = "queued"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"


class ParseStatus(str, Enum):
	PENDING = "pending"
	RECEIVED = "received"  # legacy alias; DB constraint uses 'pending'
	QUEUED = "queued"
	PROCESSING = "processing"
	READY = "ready"
	PARSED = "parsed"
	FAILED = "failed"
	CANCELLED = "cancelled"
	SUPERSEDED = "superseded"


class Tenant(Base):
	__tablename__ = "tenants"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
	name: Mapped[str] = mapped_column(String(256), nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
	)


class User(Base):
	__tablename__ = "users"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)
	email: Mapped[str] = mapped_column(String(320), nullable=False)
	display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
		Index("ix_users_tenant_id", "tenant_id"),
		Index("ix_users_is_active", "is_active"),
	)


def sha256_hex(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def metadata_sha256(metadata: Dict[str, Any]) -> str:
	return sha256_hex(canonical_json_bytes(metadata))


class Policy(Base):
	__tablename__ = "policies"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)
	external_id: Mapped[str] = mapped_column(String(128), nullable=False)
	name: Mapped[str] = mapped_column(String(512), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=PolicyStatus.DRAFT.value)

	jurisdiction: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	category: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

	current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True
	)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
	)
	updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
	)

	versions: Mapped[List[PolicyVersion]] = relationship(
		back_populates="policy",
		cascade="all, delete-orphan",
		passive_deletes=True,
		foreign_keys="PolicyVersion.policy_id",
		order_by="PolicyVersion.version_number",
	)
	current_version: Mapped[Optional[PolicyVersion]] = relationship(
		foreign_keys=[current_version_id],
		post_update=True,
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "external_id", name="uq_policies_tenant_id_external_id"),
		CheckConstraint("status in ('draft','active','retired')", name="ck_policies_status"),
		Index("ix_policies_tenant_id", "tenant_id"),
		Index("ix_policies_status", "status"),
	)


class IngestBatch(Base):
	__tablename__ = "ingest_batches"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)
	submitted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
	)
	source_system: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=IngestionBatchStatus.RECEIVED.value)
	status_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
	)

	policy_versions: Mapped[List[PolicyVersion]] = relationship(
		back_populates="ingestion_batch",
		passive_deletes=True,
	)

	__table_args__ = (
		CheckConstraint(
			"status in ('received','queued','processing','completed','failed')",
			name="ck_ingest_batches_status",
		),
		Index("ix_ingest_batches_tenant_id", "tenant_id"),
		Index("ix_ingest_batches_status", "status"),
		Index("ix_ingest_batches_created_at", "created_at"),
	)


class PolicyVersion(Base):
	__tablename__ = "policy_versions"
	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

	policy_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False
	)
	version_number: Mapped[int] = mapped_column(Integer, nullable=False)
	version_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	supersedes_policy_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True
	)

	title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
	effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

	blob_container: Mapped[str] = mapped_column(String(128), nullable=False)
	blob_name: Mapped[str] = mapped_column(String(1024), nullable=False)
	blob_version_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
	blob_etag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	content_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

	extracted_blob_container: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	extracted_blob_name: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
	extracted_blob_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
	metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
	metadata_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

	ingest_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("ingest_batches.id", ondelete="SET NULL"), nullable=True
	)

	parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default=ParseStatus.PENDING.value)
	is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
	parse_status_updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now()
	)
	parse_error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	parse_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
	)
	correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

	policy: Mapped[Policy] = relationship(back_populates="versions", foreign_keys=[policy_id])
	ingestion_batch: Mapped[Optional[IngestBatch]] = relationship(back_populates="policy_versions")

	sections: Mapped[List[PolicySection]] = relationship(
		back_populates="policy_version",
		cascade="all, delete-orphan",
		passive_deletes=True,
		order_by="PolicySection.section_index",
	)
	__table_args__ = (
		UniqueConstraint("policy_id", "version_number", name="uq_policy_versions_policy_id_version_number"),
		# Enforce an optional client-provided label to be unique per policy.
		Index(
			"uq_policy_versions_policy_id_version_label",
			"policy_id",
			"version_label",
			unique=True,
			postgresql_where=(version_label.isnot(None)),
		),
		UniqueConstraint(
			"policy_id",
			"content_sha256",
			"metadata_sha256",
			name="uq_policy_versions_policy_id_content_sha256_metadata_sha256",
		),
		CheckConstraint("version_number >= 1", name="version_number_gte_1"),
		CheckConstraint(
			"parse_status in ('pending','queued','processing','ready','parsed','failed','cancelled','superseded')",
			name="parse_status_allowed",
		),
		Index("ix_policy_versions_policy_id_created_at", "policy_id", "created_at"),
		Index("ix_policy_versions_content_sha256", "content_sha256"),
		Index("ix_policy_versions_parse_status", "parse_status"),
		Index("ix_policy_versions_is_current", "is_current"),
	)


class PolicySection(Base):
	__tablename__ = "policy_sections"
	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

	policy_version_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="CASCADE"), nullable=False
	)

	section_index: Mapped[int] = mapped_column(Integer, nullable=False)
	section_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
	title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
	text: Mapped[str] = mapped_column(Text, nullable=False)

	start_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
	end_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

	content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

	rag_document_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
	rag_node_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

	policy_version: Mapped[PolicyVersion] = relationship(back_populates="sections")

	__table_args__ = (
		UniqueConstraint(
			"policy_version_id",
			"section_index",
			name="uq_policy_sections_policy_version_id_section_index",
		),
		Index("ix_policy_sections_policy_version_id", "policy_version_id"),
		Index("ix_policy_sections_content_sha256", "content_sha256"),
		Index("ix_policy_sections_tenant_id", "tenant_id"),
		CheckConstraint("section_index >= 0", name="section_index_gte_0"),
	)


class IngestItem(Base):
	__tablename__ = "ingest_items"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

	tenant_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)
	batch_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), ForeignKey("ingest_batches.id", ondelete="CASCADE"), nullable=False
	)
	policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True
	)

	blob_container: Mapped[str] = mapped_column(String(128), nullable=False)
	blob_name: Mapped[str] = mapped_column(String(1024), nullable=False)
	blob_version_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
	blob_etag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	content_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

	content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
	metadata_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

	correlation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=IngestionBatchStatus.RECEIVED.value)
	error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
	error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
	result_policy_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
		UUID(as_uuid=True), ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True
	)

	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
	)

	__table_args__ = (
		CheckConstraint(
			"status in ('received','queued','processing','completed','failed')",
			name="ck_ingest_items_status",
		),
		Index("ix_ingest_items_tenant_id", "tenant_id"),
		Index("ix_ingest_items_batch_id", "batch_id"),
		Index("ix_ingest_items_policy_id", "policy_id"),
		Index("ix_ingest_items_status", "status"),
		Index("ix_ingest_items_content_sha256", "content_sha256"),
	)


# -----------------------------
# Pydantic API contracts
# -----------------------------

try:
	from pydantic import BaseModel, ConfigDict, Field

	_PYDANTIC_V2 = True
except Exception:  # pragma: no cover
	from pydantic import BaseModel, Field  # type: ignore

	ConfigDict = None  # type: ignore
	_PYDANTIC_V2 = False


class _APIModel(BaseModel):
	if _PYDANTIC_V2:
		model_config = ConfigDict(extra="forbid", from_attributes=True)
	else:  # pragma: no cover

		class Config:  # type: ignore
			extra = "forbid"
			orm_mode = True


class PolicyCreateRequest(_APIModel):
	tenant_id: uuid.UUID
	external_id: str = Field(min_length=1, max_length=128)
	name: str = Field(min_length=1, max_length=512)
	jurisdiction: Optional[str] = Field(default=None, max_length=128)
	category: Optional[str] = Field(default=None, max_length=256)
	created_by_user_id: Optional[uuid.UUID] = None


class PolicyResponse(_APIModel):
	id: uuid.UUID
	tenant_id: uuid.UUID
	external_id: str
	name: str
	status: str
	jurisdiction: Optional[str]
	category: Optional[str]
	current_version_id: Optional[uuid.UUID]
	created_at: datetime
	created_by_user_id: Optional[uuid.UUID]
	updated_at: datetime
	updated_by_user_id: Optional[uuid.UUID]


class IngestionBatchCreateRequest(_APIModel):
	tenant_id: uuid.UUID
	source_system: Optional[str] = Field(default=None, max_length=128)
	submitted_by_user_id: Optional[uuid.UUID] = None
	correlation_id: Optional[str] = Field(default=None, max_length=128)


class IngestionBatchResponse(_APIModel):
	id: uuid.UUID
	tenant_id: uuid.UUID
	source_system: Optional[str]
	submitted_by_user_id: Optional[uuid.UUID]
	status: str
	status_reason: Optional[str]
	correlation_id: Optional[str]
	created_at: datetime
	updated_at: datetime


class PolicyVersionCreateRequest(_APIModel):
	tenant_id: uuid.UUID
	policy_id: uuid.UUID

	blob_container: str = Field(min_length=1, max_length=128)
	blob_name: str = Field(min_length=1, max_length=1024)
	blob_version_id: Optional[str] = Field(default=None, max_length=256)
	blob_etag: Optional[str] = Field(default=None, max_length=128)
	content_type: Optional[str] = Field(default=None, max_length=128)
	content_length: Optional[int] = Field(default=None, ge=0)

	# The API submits metadata; the service layer should compute the sha256.
	metadata: Dict[str, Any] = Field(default_factory=dict)

	# Optional precomputed hashes (useful for worker-driven ingestion)
	content_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)
	metadata_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)

	ingest_batch_id: Optional[uuid.UUID] = None
	created_by_user_id: Optional[uuid.UUID] = None
	correlation_id: Optional[str] = Field(default=None, max_length=128)

	title: Optional[str] = Field(default=None, max_length=512)
	effective_date: Optional[date] = None


class PolicyVersionResponse(_APIModel):
	id: uuid.UUID
	tenant_id: uuid.UUID
	policy_id: uuid.UUID
	version_number: int
	version_label: Optional[str] = None

	title: Optional[str]
	effective_date: Optional[date]

	blob_container: str
	blob_name: str
	raw_blob_uri: Optional[str] = None
	blob_version_id: Optional[str]
	blob_etag: Optional[str]
	content_type: Optional[str]
	content_length: Optional[int]

	extracted_blob_container: Optional[str] = None
	extracted_blob_name: Optional[str] = None
	extracted_blob_uri: Optional[str] = None

	content_sha256: str
	metadata_json: Dict[str, Any]
	metadata_sha256: str

	ingest_batch_id: Optional[uuid.UUID]

	parse_status: str
	parse_status_updated_at: datetime
	parse_error_code: Optional[str]
	parse_error_message: Optional[str]

	is_current: bool = False
	supersedes_policy_version_id: Optional[uuid.UUID] = None

	created_at: datetime
	created_by_user_id: Optional[uuid.UUID]
	correlation_id: Optional[str]


class PolicySectionResponse(_APIModel):
	id: uuid.UUID
	tenant_id: uuid.UUID
	policy_version_id: uuid.UUID
	section_index: int
	section_path: Optional[str]
	title: Optional[str]
	text: str
	start_offset: Optional[int]
	end_offset: Optional[int]
	content_sha256: str
	rag_document_id: Optional[str]
	rag_node_id: Optional[str]
	created_at: datetime

