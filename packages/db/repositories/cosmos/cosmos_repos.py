"""Cosmos DB NoSQL implementations of all repository interfaces.

Document model:
- Container `policies`: one document per policy, with versions and sections
  denormalized as nested arrays. Partition key: /tenant_id.
- Container `audit_logs`: one document per audit event.
- Container `embeddings`: one document per embedding vector (DiskANN indexed).
- Container `references`: one document per reference.
- Container `ingest_batches`: one document per batch, items as nested array.

All IDs are stored as strings (Cosmos uses string `id`). Conversion to/from
uuid.UUID happens at the repository boundary.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from packages.db.repositories.base import (
    IAuditRepository,
    IEmbeddingRepository,
    IIngestBatchRepository,
    IIngestItemRepository,
    IPolicyRepository,
    IPolicySectionRepository,
    IPolicyVersionRepository,
    IReferenceRepository,
)
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid_str(val: Any) -> str:
    return str(val) if val else ""


def _to_uuid(val: Any) -> Optional[uuid.UUID]:
    if val is None or val == "":
        return None
    return uuid.UUID(str(val))


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val))


def _parse_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val))


# ---------------------------------------------------------------------------
# Helpers to convert Cosmos documents to DTOs
# ---------------------------------------------------------------------------


def _doc_to_policy_dto(doc: Dict[str, Any]) -> PolicyDTO:
    return PolicyDTO(
        id=uuid.UUID(doc["id"]),
        tenant_id=_to_uuid(doc["tenant_id"]),
        external_id=doc["external_id"],
        name=doc["name"],
        status=doc.get("status", "draft"),
        jurisdiction=doc.get("jurisdiction"),
        category=doc.get("category"),
        authority_level=doc.get("authority_level", 0),
        department_scope=doc.get("department_scope", "all"),
        policy_type=doc.get("policy_type"),
        current_version_id=_to_uuid(doc.get("current_version_id")),
        created_at=_parse_dt(doc.get("created_at")),
        created_by_user_id=_to_uuid(doc.get("created_by_user_id")),
        updated_at=_parse_dt(doc.get("updated_at")),
        updated_by_user_id=_to_uuid(doc.get("updated_by_user_id")),
    )


def _version_dict_to_dto(v: Dict[str, Any], tenant_id: uuid.UUID, policy_id: uuid.UUID) -> PolicyVersionDTO:
    return PolicyVersionDTO(
        id=uuid.UUID(v["id"]),
        tenant_id=tenant_id,
        policy_id=policy_id,
        version_number=v["version_number"],
        version_label=v.get("version_label"),
        supersedes_policy_version_id=_to_uuid(v.get("supersedes_policy_version_id")),
        title=v.get("title"),
        effective_date=_parse_date(v.get("effective_date")),
        blob_container=v.get("blob_container", ""),
        blob_name=v.get("blob_name", ""),
        blob_version_id=v.get("blob_version_id"),
        blob_etag=v.get("blob_etag"),
        content_type=v.get("content_type"),
        content_length=v.get("content_length"),
        extracted_blob_container=v.get("extracted_blob_container"),
        extracted_blob_name=v.get("extracted_blob_name"),
        extracted_blob_uri=v.get("extracted_blob_uri"),
        content_sha256=v.get("content_sha256", ""),
        metadata_json=v.get("metadata_json", {}),
        metadata_sha256=v.get("metadata_sha256", ""),
        ingest_batch_id=_to_uuid(v.get("ingest_batch_id")),
        parse_status=v.get("parse_status", "pending"),
        is_current=v.get("is_current", False),
        parse_status_updated_at=_parse_dt(v.get("parse_status_updated_at")),
        parse_error_code=v.get("parse_error_code"),
        parse_error_message=v.get("parse_error_message"),
        created_at=_parse_dt(v.get("created_at")),
        created_by_user_id=_to_uuid(v.get("created_by_user_id")),
        correlation_id=v.get("correlation_id"),
    )


def _section_dict_to_dto(s: Dict[str, Any], tenant_id: uuid.UUID, pv_id: uuid.UUID) -> PolicySectionDTO:
    return PolicySectionDTO(
        id=uuid.UUID(s["id"]),
        tenant_id=tenant_id,
        policy_version_id=pv_id,
        section_index=s["section_index"],
        section_path=s.get("section_path"),
        title=s.get("title"),
        text=s["text"],
        start_offset=s.get("start_offset"),
        end_offset=s.get("end_offset"),
        content_sha256=s.get("content_sha256", ""),
        rag_document_id=s.get("rag_document_id"),
        rag_node_id=s.get("rag_node_id"),
        created_at=_parse_dt(s.get("created_at")),
    )


# ---------------------------------------------------------------------------
# Policy Repository
# ---------------------------------------------------------------------------


class CosmosPolicyRepository(IPolicyRepository):
    def __init__(self, container: Any) -> None:
        self._c = container

    def get_by_id(self, *, policy_id: uuid.UUID) -> Optional[PolicyDTO]:
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(policy_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return _doc_to_policy_dto(items[0]) if items else None

    def get_by_external_id(self, *, tenant_id: uuid.UUID, external_id: str) -> Optional[PolicyDTO]:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid AND c.external_id = @eid"
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@eid", "value": external_id},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return _doc_to_policy_dto(items[0]) if items else None

    def list_for_tenant(self, *, tenant_id: uuid.UUID) -> List[PolicyDTO]:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid ORDER BY c.created_at DESC"
        params = [{"name": "@tid", "value": str(tenant_id)}]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [_doc_to_policy_dto(i) for i in items]

    def create(self, *, tenant_id: uuid.UUID, external_id: str, name: str, status: str = "draft",
               jurisdiction: Optional[str] = None, category: Optional[str] = None,
               authority_level: int = 0, department_scope: str = "all",
               policy_type: Optional[str] = None, created_by_user_id: Optional[uuid.UUID] = None) -> PolicyDTO:
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "external_id": external_id,
            "name": name,
            "status": status,
            "jurisdiction": jurisdiction,
            "category": category,
            "authority_level": authority_level,
            "department_scope": department_scope,
            "policy_type": policy_type,
            "current_version_id": None,
            "created_by_user_id": _uuid_str(created_by_user_id) or None,
            "updated_by_user_id": _uuid_str(created_by_user_id) or None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "versions": [],
        }
        self._c.upsert_item(doc)
        return _doc_to_policy_dto(doc)

    def update(self, *, policy_id: uuid.UUID, **kwargs: Any) -> Optional[PolicyDTO]:
        dto = self.get_by_id(policy_id=policy_id)
        if dto is None:
            return None
        # Re-read the full document to update it
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(policy_id)}]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(dto.tenant_id)))
        if not items:
            return None
        doc = items[0]
        sentinel = object()
        for key in ("current_version_id", "policy_type", "department_scope", "authority_level", "updated_by_user_id"):
            val = kwargs.get(key, sentinel)
            if val is not sentinel:
                doc[key] = _uuid_str(val) if key.endswith("_id") and val is not None else val
        doc["updated_at"] = _now_iso()
        self._c.upsert_item(doc)
        return _doc_to_policy_dto(doc)


# ---------------------------------------------------------------------------
# Policy Version Repository
# ---------------------------------------------------------------------------


class CosmosPolicyVersionRepository(IPolicyVersionRepository):
    """Versions are stored as nested documents inside the policy document."""

    def __init__(self, container: Any) -> None:
        self._c = container

    def _get_policy_doc(self, policy_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(policy_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None

    def _find_version(self, policy_doc: Dict[str, Any], version_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        for v in policy_doc.get("versions", []):
            if v["id"] == str(version_id):
                return v
        return None

    def get_by_id(self, *, version_id: uuid.UUID) -> Optional[PolicyVersionDTO]:
        # Cross-partition scan for version by ID (search all policies)
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.versions, {'id': @vid}, true)"
        params = [{"name": "@vid", "value": str(version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return None
        doc = items[0]
        v = self._find_version(doc, version_id)
        if v is None:
            return None
        return _version_dict_to_dto(v, _to_uuid(doc["tenant_id"]), uuid.UUID(doc["id"]))

    def list_for_policy(self, *, tenant_id: uuid.UUID, policy_id: uuid.UUID) -> List[PolicyVersionDTO]:
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            return []
        versions = sorted(doc.get("versions", []), key=lambda v: v.get("version_number", 0), reverse=True)
        return [_version_dict_to_dto(v, _to_uuid(doc["tenant_id"]), uuid.UUID(doc["id"])) for v in versions]

    def exists_duplicate(self, *, policy_id: uuid.UUID, content_sha256: str, metadata_sha256: str) -> Optional[uuid.UUID]:
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            return None
        for v in doc.get("versions", []):
            if v.get("content_sha256") == content_sha256 and v.get("metadata_sha256") == metadata_sha256:
                return uuid.UUID(v["id"])
        return None

    def next_version_number(self, *, policy_id: uuid.UUID) -> int:
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            return 1
        versions = doc.get("versions", [])
        if not versions:
            return 1
        return max(v.get("version_number", 0) for v in versions) + 1

    def latest_version_id(self, *, policy_id: uuid.UUID) -> Optional[uuid.UUID]:
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            return None
        versions = doc.get("versions", [])
        if not versions:
            return None
        latest = max(versions, key=lambda v: v.get("version_number", 0))
        return uuid.UUID(latest["id"])

    def create(self, **fields: Any) -> PolicyVersionDTO:
        policy_id = fields.get("policy_id")
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            raise ValueError(f"Policy {policy_id} not found")
        version_doc = {
            "id": str(fields.get("id", uuid.uuid4())),
            "version_number": fields["version_number"],
            "version_label": fields.get("version_label"),
            "supersedes_policy_version_id": _uuid_str(fields.get("supersedes_policy_version_id")) or None,
            "title": fields.get("title"),
            "effective_date": str(fields["effective_date"]) if fields.get("effective_date") else None,
            "blob_container": fields.get("blob_container", ""),
            "blob_name": fields.get("blob_name", ""),
            "blob_version_id": fields.get("blob_version_id"),
            "blob_etag": fields.get("blob_etag"),
            "content_type": fields.get("content_type"),
            "content_length": fields.get("content_length"),
            "content_sha256": fields.get("content_sha256", ""),
            "metadata_json": fields.get("metadata_json", {}),
            "metadata_sha256": fields.get("metadata_sha256", ""),
            "ingest_batch_id": _uuid_str(fields.get("ingest_batch_id")) or None,
            "parse_status": fields.get("parse_status", "pending"),
            "is_current": fields.get("is_current", False),
            "parse_status_updated_at": _now_iso(),
            "parse_error_code": None,
            "parse_error_message": None,
            "created_at": _now_iso(),
            "created_by_user_id": _uuid_str(fields.get("created_by_user_id")) or None,
            "correlation_id": fields.get("correlation_id"),
        }
        doc.setdefault("versions", []).append(version_doc)
        self._c.upsert_item(doc)
        return _version_dict_to_dto(version_doc, _to_uuid(doc["tenant_id"]), uuid.UUID(doc["id"]))

    def set_parse_status(self, *, version_id: uuid.UUID, status: str,
                         error_code: Optional[str] = None, error_message: Optional[str] = None) -> None:
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.versions, {'id': @vid}, true)"
        params = [{"name": "@vid", "value": str(version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return
        doc = items[0]
        for v in doc.get("versions", []):
            if v["id"] == str(version_id):
                v["parse_status"] = status
                v["parse_status_updated_at"] = _now_iso()
                v["parse_error_code"] = error_code
                v["parse_error_message"] = error_message
                break
        self._c.upsert_item(doc)

    def set_current(self, *, policy_id: uuid.UUID, version_id: uuid.UUID) -> None:
        doc = self._get_policy_doc(policy_id)
        if doc is None:
            return
        for v in doc.get("versions", []):
            v["is_current"] = (v["id"] == str(version_id))
        doc["current_version_id"] = str(version_id)
        self._c.upsert_item(doc)

    def set_extracted_blob(self, *, version_id: uuid.UUID, extracted_blob_container: str,
                           extracted_blob_name: str, extracted_blob_uri: str) -> None:
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.versions, {'id': @vid}, true)"
        params = [{"name": "@vid", "value": str(version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return
        doc = items[0]
        for v in doc.get("versions", []):
            if v["id"] == str(version_id):
                v["extracted_blob_container"] = extracted_blob_container
                v["extracted_blob_name"] = extracted_blob_name
                v["extracted_blob_uri"] = extracted_blob_uri
                break
        self._c.upsert_item(doc)


# ---------------------------------------------------------------------------
# Section Repository
# ---------------------------------------------------------------------------


class CosmosPolicySectionRepository(IPolicySectionRepository):
    """Sections are standalone documents in the 'sections' container.

    Avoids Cosmos 2MB doc limit for policies with many large sections.
    """

    def __init__(self, sections_container: Any, policies_container: Any) -> None:
        self._c = sections_container
        self._policies = policies_container

    def list_for_version(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID,
                         limit: int = 20, offset: int = 0) -> List[PolicySectionDTO]:
        query = ("SELECT * FROM c WHERE c.tenant_id = @tid AND c.policy_version_id = @pvid "
                 "ORDER BY c.section_index ASC OFFSET @off LIMIT @lim")
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@pvid", "value": str(policy_version_id)},
            {"name": "@off", "value": offset},
            {"name": "@lim", "value": limit},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [_section_dict_to_dto(s, tenant_id, policy_version_id) for s in items]

    def get_detail(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> Optional[SectionDetailDTO]:
        # Get the section
        query = "SELECT * FROM c WHERE c.id = @sid AND c.tenant_id = @tid"
        params = [
            {"name": "@sid", "value": str(section_id)},
            {"name": "@tid", "value": str(tenant_id)},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        if not items:
            return None
        s = items[0]
        pv_id = s["policy_version_id"]

        # Find the parent policy+version
        pquery = "SELECT * FROM c WHERE c.tenant_id = @tid AND ARRAY_CONTAINS(c.versions, {'id': @vid}, true)"
        pparams = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@vid", "value": pv_id},
        ]
        pdocs = list(self._policies.query_items(query=pquery, parameters=pparams, partition_key=str(tenant_id)))
        if not pdocs:
            return None
        doc = pdocs[0]
        v_data = next((v for v in doc.get("versions", []) if v["id"] == pv_id), {})
        metadata = v_data.get("metadata_json", {})
        public_url = metadata.get("source_url") or metadata.get("public_url") or metadata.get("url")

        return SectionDetailDTO(
            section_id=uuid.UUID(s["id"]),
            tenant_id=tenant_id,
            policy_id=uuid.UUID(doc["id"]),
            policy_version_id=uuid.UUID(pv_id),
            policy_name=doc["name"],
            section_index=s["section_index"],
            section_path=s.get("section_path"),
            section_title=s.get("title"),
            text=s["text"],
            effective_date=_parse_date(v_data.get("effective_date")),
            is_current=v_data.get("is_current", False),
            public_url=public_url,
            metadata=metadata,
        )

    def bulk_insert(self, sections: List[Dict[str, Any]]) -> int:
        count = 0
        for s in sections:
            doc = {
                "id": str(s.get("id", uuid.uuid4())),
                "tenant_id": str(s["tenant_id"]),
                "policy_version_id": str(s["policy_version_id"]),
                "section_index": s["section_index"],
                "section_path": s.get("section_path"),
                "title": s.get("title"),
                "text": s["text"],
                "start_offset": s.get("start_offset"),
                "end_offset": s.get("end_offset"),
                "content_sha256": s.get("content_sha256", ""),
                "rag_document_id": s.get("rag_document_id"),
                "rag_node_id": s.get("rag_node_id"),
                "created_at": _now_iso(),
            }
            self._c.upsert_item(doc)
            count += 1
        return count

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        query = "SELECT c.id, c.tenant_id FROM c WHERE c.policy_version_id = @pvid"
        params = [{"name": "@pvid", "value": str(policy_version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        for item in items:
            self._c.delete_item(item=item["id"], partition_key=item["tenant_id"])
        return len(items)

    def exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        query = "SELECT c.id FROM c WHERE c.id = @sid AND c.tenant_id = @tid"
        params = [
            {"name": "@sid", "value": str(section_id)},
            {"name": "@tid", "value": str(tenant_id)},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return len(items) > 0


# ---------------------------------------------------------------------------
# Embedding Repository
# ---------------------------------------------------------------------------


class CosmosEmbeddingRepository(IEmbeddingRepository):
    def __init__(self, container: Any) -> None:
        self._c = container

    def bulk_insert(self, embeddings: List[Dict[str, Any]]) -> int:
        count = 0
        for e in embeddings:
            doc = {
                "id": str(e.get("id", uuid.uuid4())),
                "tenant_id": str(e["tenant_id"]),
                "policy_version_id": str(e["policy_version_id"]),
                "policy_section_id": str(e["policy_section_id"]),
                "embedding_model": e["embedding_model"],
                "embedding": list(e["embedding"]),  # float array for DiskANN
                "content_sha256": e.get("content_sha256"),
                "authority_level": e.get("authority_level"),
                "department_scope": e.get("department_scope"),
                "policy_type": e.get("policy_type"),
                "effective_date": str(e["effective_date"]) if e.get("effective_date") else None,
                "created_at": _now_iso(),
            }
            self._c.upsert_item(doc)
            count += 1
        return count

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        query = "SELECT c.id, c.tenant_id FROM c WHERE c.policy_version_id = @pvid"
        params = [{"name": "@pvid", "value": str(policy_version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        count = 0
        for item in items:
            self._c.delete_item(item=item["id"], partition_key=item["tenant_id"])
            count += 1
        return count


# ---------------------------------------------------------------------------
# Audit Repository
# ---------------------------------------------------------------------------


class CosmosAuditRepository(IAuditRepository):
    def __init__(self, container: Any) -> None:
        self._c = container

    def write(self, *, tenant_id: uuid.UUID, event_type: str,
              correlation_id: Optional[str], payload: Dict[str, Any]) -> uuid.UUID:
        doc_id = uuid.uuid4()
        doc = {
            "id": str(doc_id),
            "tenant_id": str(tenant_id),
            "event_type": event_type,
            "correlation_id": correlation_id,
            "payload": payload,
            "created_at": _now_iso(),
        }
        self._c.upsert_item(doc)
        return doc_id

    def get_by_id(self, *, tenant_id: uuid.UUID, audit_id: uuid.UUID) -> Optional[AuditLogDTO]:
        query = "SELECT * FROM c WHERE c.id = @id AND c.tenant_id = @tid"
        params = [
            {"name": "@id", "value": str(audit_id)},
            {"name": "@tid", "value": str(tenant_id)},
        ]
        items = list(
            self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id))
        )
        if not items:
            return None
        d = items[0]
        return AuditLogDTO(
            id=uuid.UUID(d["id"]),
            tenant_id=_to_uuid(d["tenant_id"]),
            event_type=d["event_type"],
            payload=d.get("payload", {}),
            correlation_id=d.get("correlation_id"),
            created_at=_parse_dt(d.get("created_at")),
        )

    def list_for_tenant(self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0) -> List[AuditLogDTO]:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid ORDER BY c.created_at DESC OFFSET @off LIMIT @lim"
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@off", "value": offset},
            {"name": "@lim", "value": limit},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [
            AuditLogDTO(
                id=uuid.UUID(d["id"]),
                tenant_id=_to_uuid(d["tenant_id"]),
                event_type=d["event_type"],
                payload=d.get("payload", {}),
                correlation_id=d.get("correlation_id"),
                created_at=_parse_dt(d.get("created_at")),
            )
            for d in items
        ]


# ---------------------------------------------------------------------------
# Ingest Batch / Item Repositories
# ---------------------------------------------------------------------------


class CosmosIngestBatchRepository(IIngestBatchRepository):
    def __init__(self, container: Any) -> None:
        self._c = container

    def get(self, batch_id: uuid.UUID) -> Optional[IngestBatchDTO]:
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(batch_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return None
        b = items[0]
        return IngestBatchDTO(
            id=uuid.UUID(b["id"]),
            tenant_id=_to_uuid(b["tenant_id"]),
            status=b["status"],
            submitted_by_user_id=_to_uuid(b.get("submitted_by_user_id")),
            source_system=b.get("source_system"),
            status_reason=b.get("status_reason"),
            correlation_id=b.get("correlation_id"),
            created_at=_parse_dt(b.get("created_at")),
            updated_at=_parse_dt(b.get("updated_at")),
        )

    def create(self, **fields: Any) -> IngestBatchDTO:
        doc_id = uuid.uuid4()
        doc = {
            "id": str(doc_id),
            "tenant_id": str(fields["tenant_id"]),
            "status": fields.get("status", "received"),
            "submitted_by_user_id": _uuid_str(fields.get("submitted_by_user_id")) or None,
            "source_system": fields.get("source_system"),
            "status_reason": fields.get("status_reason"),
            "correlation_id": fields.get("correlation_id"),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "items": [],
        }
        self._c.upsert_item(doc)
        return IngestBatchDTO(
            id=doc_id,
            tenant_id=_to_uuid(doc["tenant_id"]),
            status=doc["status"],
            submitted_by_user_id=_to_uuid(doc.get("submitted_by_user_id")),
            source_system=doc.get("source_system"),
            correlation_id=doc.get("correlation_id"),
            created_at=_parse_dt(doc["created_at"]),
            updated_at=_parse_dt(doc["updated_at"]),
        )

    def update_status(self, *, batch_id: uuid.UUID, status: str) -> None:
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(batch_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return
        doc = items[0]
        doc["status"] = status
        doc["updated_at"] = _now_iso()
        self._c.upsert_item(doc)


class CosmosIngestItemRepository(IIngestItemRepository):
    """Items are stored as nested documents inside ingest_batches."""

    def __init__(self, container: Any) -> None:
        self._c = container

    def create(self, **fields: Any) -> IngestItemDTO:
        batch_id = str(fields["batch_id"])
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": batch_id}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            raise ValueError(f"Batch {batch_id} not found")
        doc = items[0]
        item_id = uuid.uuid4()
        item_doc = {
            "id": str(item_id),
            "tenant_id": str(fields["tenant_id"]),
            "batch_id": batch_id,
            "status": fields.get("status", "received"),
            "policy_id": _uuid_str(fields.get("policy_id")) or None,
            "blob_container": fields.get("blob_container"),
            "blob_name": fields.get("blob_name"),
            "content_sha256": fields.get("content_sha256"),
            "metadata_json": fields.get("metadata_json", {}),
            "metadata_sha256": fields.get("metadata_sha256"),
            "correlation_id": fields.get("correlation_id"),
            "error_code": None,
            "error_message": None,
            "result_policy_version_id": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        doc.setdefault("items", []).append(item_doc)
        self._c.upsert_item(doc)
        return IngestItemDTO(
            id=item_id,
            tenant_id=_to_uuid(item_doc["tenant_id"]),
            batch_id=uuid.UUID(batch_id),
            status=item_doc["status"],
            policy_id=_to_uuid(item_doc.get("policy_id")),
            created_at=_parse_dt(item_doc["created_at"]),
            updated_at=_parse_dt(item_doc["updated_at"]),
        )

    def set_status(self, *, item_id: uuid.UUID, status: str,
                   error_code: Optional[str] = None, error_message: Optional[str] = None,
                   result_policy_version_id: Optional[uuid.UUID] = None) -> None:
        # Scan batches for the item
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.items, {'id': @iid}, true)"
        params = [{"name": "@iid", "value": str(item_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return
        doc = items[0]
        for it in doc.get("items", []):
            if it["id"] == str(item_id):
                it["status"] = status
                it["error_code"] = error_code
                it["error_message"] = error_message
                if result_policy_version_id is not None:
                    it["result_policy_version_id"] = str(result_policy_version_id)
                it["updated_at"] = _now_iso()
                break
        self._c.upsert_item(doc)

    def set_status_by_result_version(self, *, policy_version_id: uuid.UUID, status: str,
                                     error_code: Optional[str] = None,
                                     error_message: Optional[str] = None) -> None:
        pvid = str(policy_version_id)
        query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.items, {'result_policy_version_id': @pvid}, true)"
        params = [{"name": "@pvid", "value": pvid}]
        docs = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        for doc in docs:
            changed = False
            for it in doc.get("items", []):
                if it.get("result_policy_version_id") == pvid:
                    it["status"] = status
                    it["error_code"] = error_code
                    it["error_message"] = error_message
                    it["updated_at"] = _now_iso()
                    changed = True
            if changed:
                self._c.upsert_item(doc)

    def count_active_for_batch(self, *, batch_id: uuid.UUID) -> int:
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": str(batch_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if not items:
            return 0
        doc = items[0]
        return sum(1 for it in doc.get("items", []) if it.get("status") in ("received", "queued", "processing"))


# ---------------------------------------------------------------------------
# Reference Repository
# ---------------------------------------------------------------------------


class CosmosReferenceRepository(IReferenceRepository):
    def __init__(self, container: Any, policies_container: Any, sections_container: Any = None) -> None:
        self._c = container
        self._policies = policies_container
        self._sections = sections_container

    def bulk_insert(self, refs: List[Dict[str, Any]]) -> int:
        count = 0
        for ref in refs:
            if isinstance(ref, dict):
                doc = dict(ref)
            else:
                # ORM model — extract attributes
                doc = {
                    "source_section_id": str(ref.source_section_id),
                    "source_policy_version_id": str(ref.source_policy_version_id),
                    "tenant_id": str(ref.tenant_id),
                    "reference_type": ref.reference_type,
                    "resolution_status": ref.resolution_status,
                    "matched_text": ref.matched_text,
                    "match_offset": ref.match_offset,
                    "extractor_version": ref.extractor_version,
                    "confidence": ref.confidence,
                    "target_section_id": _uuid_str(ref.target_section_id) or None,
                    "target_policy_id": _uuid_str(ref.target_policy_id) or None,
                    "target_external_uri": ref.target_external_uri,
                    "target_external_label": ref.target_external_label,
                }
            doc.setdefault("id", str(uuid.uuid4()))
            doc.setdefault("tenant_id", doc.get("tenant_id", ""))
            doc["tenant_id"] = str(doc["tenant_id"])
            for key in ("source_section_id", "source_policy_version_id", "target_section_id", "target_policy_id"):
                if doc.get(key):
                    doc[key] = str(doc[key])
            doc.setdefault("created_at", _now_iso())
            self._c.upsert_item(doc)
            count += 1
        return count

    def delete_for_section(self, *, section_id: uuid.UUID) -> int:
        query = "SELECT c.id, c.tenant_id FROM c WHERE c.source_section_id = @sid"
        params = [{"name": "@sid", "value": str(section_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        for item in items:
            self._c.delete_item(item=item["id"], partition_key=item["tenant_id"])
        return len(items)

    def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
        query = "SELECT c.id, c.tenant_id FROM c WHERE c.source_policy_version_id = @pvid"
        params = [{"name": "@pvid", "value": str(policy_version_id)}]
        items = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        for item in items:
            self._c.delete_item(item=item["id"], partition_key=item["tenant_id"])
        return len(items)

    def _to_ref_dto(self, d: Dict[str, Any]) -> PolicyReferenceDTO:
        return PolicyReferenceDTO(
            id=uuid.UUID(d["id"]),
            reference_type=d["reference_type"],
            resolution_status=d["resolution_status"],
            matched_text=d["matched_text"],
            confidence=d.get("confidence", 1.0),
            extractor_version=d.get("extractor_version", ""),
            source_section_id=_to_uuid(d["source_section_id"]),
            source_policy_version_id=_to_uuid(d["source_policy_version_id"]),
            target_section_id=_to_uuid(d.get("target_section_id")),
            target_policy_id=_to_uuid(d.get("target_policy_id")),
            target_external_uri=d.get("target_external_uri"),
            target_external_label=d.get("target_external_label"),
            match_offset=d.get("match_offset"),
            created_at=_parse_dt(d.get("created_at")),
        )

    def list_outbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> List[PolicyReferenceDTO]:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid AND c.source_section_id = @sid ORDER BY c.match_offset ASC"
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@sid", "value": str(section_id)},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [self._to_ref_dto(d) for d in items]

    def list_inbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> List[PolicyReferenceDTO]:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid AND c.target_section_id = @sid ORDER BY c.created_at ASC"
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@sid", "value": str(section_id)},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [self._to_ref_dto(d) for d in items]

    def list_for_policy_version(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID,
                                 limit: int = 50, offset: int = 0) -> List[PolicyReferenceDTO]:
        query = ("SELECT * FROM c WHERE c.tenant_id = @tid AND c.source_policy_version_id = @pvid "
                 "ORDER BY c.created_at ASC OFFSET @off LIMIT @lim")
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@pvid", "value": str(policy_version_id)},
            {"name": "@off", "value": offset},
            {"name": "@lim", "value": limit},
        ]
        items = list(self._c.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return [self._to_ref_dto(d) for d in items]

    def section_exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        if self._sections is not None:
            query = "SELECT c.id FROM c WHERE c.id = @sid AND c.tenant_id = @tid"
            params = [
                {"name": "@sid", "value": str(section_id)},
                {"name": "@tid", "value": str(tenant_id)},
            ]
            items = list(self._sections.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
            return len(items) > 0
        return False

    def policy_version_exists_for_tenant(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID) -> bool:
        query = "SELECT * FROM c WHERE c.tenant_id = @tid AND ARRAY_CONTAINS(c.versions, {'id': @vid}, true)"
        params = [
            {"name": "@tid", "value": str(tenant_id)},
            {"name": "@vid", "value": str(policy_version_id)},
        ]
        items = list(self._policies.query_items(query=query, parameters=params, partition_key=str(tenant_id)))
        return len(items) > 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_cosmos_repos(*, cosmos_client: Any, database_name: str) -> "RepositorySet":
    from packages.db.repositories.cosmos.cosmos_client_factory import get_or_create_containers
    from packages.db.repositories.factory import RepositorySet

    containers = get_or_create_containers(cosmos_client, database_name)
    return RepositorySet(
        policies=CosmosPolicyRepository(containers.policies),
        versions=CosmosPolicyVersionRepository(containers.policies),
        sections=CosmosPolicySectionRepository(containers.sections, containers.policies),
        embeddings=CosmosEmbeddingRepository(containers.embeddings),
        audit=CosmosAuditRepository(containers.audit_logs),
        ingest_batches=CosmosIngestBatchRepository(containers.ingest_batches),
        ingest_items=CosmosIngestItemRepository(containers.ingest_batches),
        references=CosmosReferenceRepository(containers.references, containers.policies, containers.sections),
    )
