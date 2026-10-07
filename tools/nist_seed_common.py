"""Helpers shared by the NIST catalog seeders (SP 800-53, CSF 2.0).

Ids are deterministic (uuid5 over a fixed namespace) so reseeding upserts in
place. The namespace and the "/"-join MUST NOT change: doing so would re-key
every seeded policy, section and embedding already in Cosmos.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

NS = uuid.UUID("11111111-2222-3333-4444-555555555555")
EMBED_MODEL = "text-embedding-3-large"
SCOPE = "all"
POLICY_TYPE = "security_control_catalog"

JsonDoc = dict[str, object]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def det_id(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def version_doc(
    *, version_id: str, version_label: str, title: str, effective_date: str, metadata: dict[str, str]
) -> JsonDoc:
    return {
        "id": version_id,
        "version_number": 1,
        "version_label": version_label,
        "title": title,
        "effective_date": effective_date,
        "blob_container": "",
        "blob_name": "",
        "content_sha256": "",
        "metadata_json": metadata,
        "metadata_sha256": "",
        "parse_status": "ready",
        "is_current": True,
        "parse_status_updated_at": now_iso(),
        "parse_error_code": None,
        "parse_error_message": None,
        "created_at": now_iso(),
        "correlation_id": None,
    }


def policy_doc(
    *,
    policy_id: str,
    tenant_id: str,
    external_id: str,
    name: str,
    category: str,
    authority_level: int,
    version: JsonDoc,
) -> JsonDoc:
    return {
        "id": policy_id,
        "tenant_id": tenant_id,
        "external_id": external_id,
        "name": name,
        "status": "active",
        "jurisdiction": "US Federal",
        "category": category,
        "authority_level": authority_level,
        "department_scope": SCOPE,
        "policy_type": POLICY_TYPE,
        "current_version_id": version["id"],
        "created_by_user_id": None,
        "updated_by_user_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "versions": [version],
    }


def section_doc(
    *,
    section_id: str,
    tenant_id: str,
    version_id: str,
    index: int,
    path: str,
    title: str,
    text: str,
) -> JsonDoc:
    return {
        "id": section_id,
        "tenant_id": tenant_id,
        "policy_version_id": version_id,
        "section_index": index,
        "section_path": path,
        "title": title,
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
        "content_sha256": sha256_text(text),
        "created_at": now_iso(),
    }


def embedding_doc(
    *,
    embedding_id: str,
    section: JsonDoc,
    policy_id: str,
    policy_name: str,
    authority_level: int,
    effective_date: str,
    public_url: str,
) -> JsonDoc:
    """Denormalized embedding doc; the 'embedding' vector is filled in by the caller."""
    return {
        "id": embedding_id,
        "tenant_id": section["tenant_id"],
        "policy_id": policy_id,
        "policy_version_id": section["policy_version_id"],
        "policy_section_id": section["id"],
        "embedding_model": EMBED_MODEL,
        "policy_name": policy_name,
        "section_title": section["title"],
        "section_path": section["section_path"],
        "section_index": section["section_index"],
        "text": section["text"],
        "authority_level": authority_level,
        "department_scope": SCOPE,
        "policy_type": POLICY_TYPE,
        "is_current": True,
        "effective_date": effective_date,
        "public_url": public_url,
        "content_sha256": section["content_sha256"],
        "created_at": now_iso(),
    }
