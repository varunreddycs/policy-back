# Policy Platform (policy-back) — Implementation Summary (as of 2026-02-27)

This repository contains the backend foundation of a **Policy-to-Production AI Compliance Platform** focused on **immutable policy versioning**, **ingestion**, and **audit-friendly traceability**, with Azure Storage used for document artifacts and queue-driven background processing.

## What’s Implemented

### 1) Database Schema (PostgreSQL) + ORM (SQLAlchemy)

- **PostgreSQL schema** created via Alembic migration: `migrations/versions/001_init.py`
- **SQLAlchemy 2.x ORM models** + Pydantic API contracts live in: `models/policy_models.py`

Core entities:
- `Tenant`, `User`
- `Policy`
  - tenant-scoped (`tenant_id`)
  - `current_version_id` pointer (set by the worker after successful extraction)
- `PolicyVersion`
  - immutable version records, content + metadata hashing
  - `parse_status` lifecycle (string + CHECK constraint)
  - `is_current` boolean with **partial unique index** so only one version per policy can be current
  - stores extracted artifact location (`extracted_blob_container`, `extracted_blob_name`, `extracted_blob_uri`)
- `PolicySection`
  - section-level extracted text with `content_sha256`
- `IngestBatch` + `IngestItem`
  - ingestion batch tracking and per-upload item tracking

Integrity + performance highlights:
- CHECK constraints emulate “enums” for statuses.
- Uniqueness constraints:
  - `policies`: (`tenant_id`, `external_id`)
  - `policy_versions`: (`policy_id`, `version_number`)
  - `policy_versions`: (`policy_id`, `content_sha256`, `metadata_sha256`) for duplicate detection
- Partial unique index: one current version per policy (`is_current = true`).

### 2) Azure Blob Storage Integration

Implemented in `services/blob_service.py`:
- `generate_upload_sas_url()` for client uploads
- `get_blob_uri()`
- `download_blob_bytes()`
- `upload_blob_bytes()` (used by the worker to upload extracted JSON)

Auth modes:
- Shared key via `AZURE_STORAGE_ACCOUNT_KEY` OR
- Entra ID via `DefaultAzureCredential` (when no key is provided)

### 3) Azure Storage Queue Integration

- Low-level publisher: `services/queue_publisher.py`
- Domain wrapper: `services/queue_service.py`

`QueueService.enqueue_policy_processing(policy_version_id)` publishes JSON messages of type:
- `policy.process.requested`

Messages include:
- `request_id` (deterministic idempotency key)
- `policy_version_id`
- `correlation_id`
- `created_at`

### 4) Ingestion Service (hashing, dedupe, version creation, enqueue)

Implemented in `services/ingestion_service.py` using repository helpers in `repositories/ingestion_repositories.py`.

Key behaviors:
- Generates ingestion batches.
- Generates upload SAS URLs.
- Registers an uploaded document by:
  - downloading blob bytes and computing `content_sha256`
  - hashing canonical JSON metadata as `metadata_sha256`
  - detecting duplicates using (`policy_id`, `content_sha256`, `metadata_sha256`)
  - creating `Policy` if missing
  - creating an immutable `PolicyVersion` with `parse_status='pending'`
  - creating `IngestItem` and linking it to the created policy version
  - enqueueing a queue message **after the DB transaction commits**

Important design decision:
- `Policy.current_version_id` is **not** set during ingestion. The **worker** sets `is_current` and `current_version_id` only after successful extraction.

### 5) FastAPI API Layer (routers + DI)

- DI wiring: `deps.py` and `db/session.py`
- Routers: `routers/ingest_router.py` and `routers/policy_router.py`
- App entrypoint: `app.py`

Endpoints implemented:
- `POST /v1/ingest/batches`
- `GET /v1/ingest/batches/{batch_id}`
- `POST /v1/ingest/batches/{batch_id}/upload-urls`
- `POST /v1/ingest/batches/{batch_id}/register`
- `GET /v1/policies`
- `GET /v1/policies/{policy_id}/versions`

Routers are intentionally thin:
- business logic remains in services
- domain exceptions are mapped to HTTP errors

### 6) Background Worker (Queue Consumer + Extraction Stub)

Implemented in `worker/policy_processor.py`.

Behavior:
- Polls Azure Storage Queue for `policy.process.requested` messages.
- Loads `PolicyVersion` from DB.
- If already `parse_status == 'ready'`, it safely no-ops (and can reconcile current pointers).
- Otherwise:
  - sets `parse_status='processing'`
  - downloads the source blob (`PolicyVersion.blob_container/blob_name`)
  - runs a deterministic **stub** extractor to create section chunks
  - writes `PolicySection` rows (clears any existing sections for idempotency)
  - uploads `extracted.json` to `policy-extracted` (configurable)
  - sets `parse_status='ready'`
  - flips `is_current=true` for this version and clears any previous current
  - updates `Policy.current_version_id`

### 7) Structured JSON Logging (Azure App Service friendly)

Implemented in:
- `core/logging_config.py`
- `core/request_context.py`
- `core/middleware.py`

Features:
- JSON log lines to stdout.
- Injects `correlation_id` and `request_id` into **every** log record using contextvars.
- Request middleware:
  - creates `request_id` per request
  - propagates/sets `correlation_id`
  - returns `X-Request-ID` and `X-Correlation-ID` response headers
  - logs one request completion event with duration + status

### 8) Swagger/OpenAPI + Export Artifact

- Swagger UI: `GET /docs`
- OpenAPI JSON: `GET /openapi.json`
- Export script: `scripts/export_openapi.py` writes `openapi.json` at repo root.

### 9) Python Dependencies

- Pinned dependency list: `requirements.txt`
  - Includes FastAPI/Uvicorn, SQLAlchemy/Alembic, Azure SDKs
  - Includes PostgreSQL driver dependency (`psycopg[binary]`)

## How to Run (local)

### API

- Start server:
  - `uvicorn app:app --host 0.0.0.0 --port 8000`

### Worker

- Run worker:
  - `python -m worker.policy_processor`

## Configuration (Environment Variables)

### Database
- `DATABASE_URL` (e.g., `postgresql+psycopg://user:pass@host:5432/db`)

### Azure Blob
- `AZURE_STORAGE_ACCOUNT_URL` or `AZURE_STORAGE_ACCOUNT_NAME`
- Optional: `AZURE_STORAGE_ACCOUNT_KEY`
- Optional: `AZURE_STORAGE_SAS_EXPIRY_MINUTES`

### Azure Queue
- `AZURE_POLICY_EXTRACTION_QUEUE_NAME`
- `AZURE_STORAGE_QUEUE_ACCOUNT_URL` (preferred)
  - fallback supported: `AZURE_STORAGE_ACCOUNT_URL` (worker converts blob endpoint to queue endpoint)

### Worker
- `AZURE_POLICY_EXTRACTED_CONTAINER` (default: `policy-extracted`)
- `WORKER_POLL_SECONDS` (default: `2`)
- `WORKER_VISIBILITY_TIMEOUT_SECONDS` (default: `60`)
- `WORKER_MAX_MESSAGES` (default: `8`)

## Known Gaps / Next Hardening Steps

This is a working foundation, but the following are not yet implemented and are expected for a production-grade, multi-tenant healthcare platform:

- **AuthN/AuthZ**: tenant identity should come from auth claims, not from client-provided `tenant_id`.
- **Outbox pattern** for enqueue reliability (avoid “DB commit but queue publish failed”).
- **Worker concurrency controls** (e.g., row/advisory locks) to reduce races when multiple workers process the same policy.
- **Poison queue handling** for messages that repeatedly fail.
- **Blob path allowlisting + tenant-scoped prefixes** to prevent SAS issuance for arbitrary containers/paths.
- **True extraction pipeline** (PDF/Doc parsing, sectioning heuristics, OCR) to replace the stub extractor.

---

If you want, the next deliverable can be a short “production hardening backlog” with prioritized items and acceptance criteria.
