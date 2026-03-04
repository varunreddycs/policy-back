# Database schema (visual)

This document reflects the canonical SQLAlchemy models under `packages/db/models/`.

## ER diagram (Mermaid)

```mermaid
erDiagram
  TENANTS {
    UUID id PK
    string slug
    string name
    boolean is_active
    datetime created_at
    datetime updated_at
  }

  USERS {
    UUID id PK
    UUID tenant_id FK
    string email
    string display_name
    boolean is_active
    datetime created_at
    datetime updated_at
  }

  POLICIES {
    UUID id PK
    UUID tenant_id FK
    string external_id
    string name
    string status
    string jurisdiction
    string category

    int authority_level
    string department_scope
    string policy_type

    UUID current_version_id FK

    datetime created_at
    UUID created_by_user_id FK
    datetime updated_at
    UUID updated_by_user_id FK
  }

  INGEST_BATCHES {
    UUID id PK
    UUID tenant_id FK
    UUID submitted_by_user_id FK
    string source_system
    string status
    string status_reason
    string correlation_id
    datetime created_at
    datetime updated_at
  }

  POLICY_VERSIONS {
    UUID id PK
    UUID tenant_id FK
    UUID policy_id FK

    int version_number
    string version_label
    UUID supersedes_policy_version_id

    string title
    date effective_date

    string blob_container
    string blob_name
    string blob_version_id
    string blob_etag
    string content_type
    int content_length

    string extracted_blob_container
    string extracted_blob_name
    string extracted_blob_uri

    string content_sha256
    jsonb metadata_json
    string metadata_sha256

    UUID ingest_batch_id FK

    string parse_status
    boolean is_current
    datetime parse_status_updated_at
    string parse_error_code
    string parse_error_message

    datetime created_at
    UUID created_by_user_id FK
    string correlation_id
  }

  POLICY_SECTIONS {
    UUID id PK
    UUID tenant_id FK
    UUID policy_version_id FK

    int section_index
    string section_path
    string title
    text text

    int start_offset
    int end_offset

    string content_sha256

    string rag_document_id
    string rag_node_id

    datetime created_at
  }

  INGEST_ITEMS {
    UUID id PK
    UUID tenant_id FK
    UUID batch_id FK
    UUID policy_id FK

    string blob_container
    string blob_name
    string blob_version_id
    string blob_etag
    string content_type
    int content_length

    string content_sha256
    jsonb metadata_json
    string metadata_sha256

    string correlation_id
    string status
    string error_code
    string error_message
    UUID result_policy_version_id FK

    datetime created_at
    datetime updated_at
  }

  AUDIT_LOGS {
    UUID id PK
    UUID tenant_id
    string correlation_id
    string event_type
    jsonb payload_json
    datetime created_at
  }

  %% Relationships
  TENANTS ||--o{ USERS : has
  TENANTS ||--o{ POLICIES : owns
  TENANTS ||--o{ INGEST_BATCHES : has
  TENANTS ||--o{ POLICY_VERSIONS : has
  TENANTS ||--o{ POLICY_SECTIONS : has
  TENANTS ||--o{ INGEST_ITEMS : has
  TENANTS ||--o{ AUDIT_LOGS : records

  USERS ||--o{ INGEST_BATCHES : submitted
  USERS ||--o{ POLICIES : created_or_updated

  POLICIES ||--o{ POLICY_VERSIONS : versions
  POLICIES ||--o| POLICY_VERSIONS : current_version

  POLICY_VERSIONS ||--o| POLICY_VERSIONS : supersedes

  INGEST_BATCHES ||--o{ POLICY_VERSIONS : produced
  INGEST_BATCHES ||--o{ INGEST_ITEMS : items

  POLICY_VERSIONS ||--o{ POLICY_SECTIONS : sections
  POLICY_VERSIONS ||--o{ INGEST_ITEMS : result
```

## Notes
- `POLICIES.current_version_id -> POLICY_VERSIONS.id` is nullable and uses `ON DELETE SET NULL`.
- `AUDIT_LOGS.tenant_id` is a tenant discriminator but is not modeled as an explicit FK in `packages/db/models/governance.py`.
- The diagram focuses on core fields + relationships; it omits many indexes/constraints for readability.
