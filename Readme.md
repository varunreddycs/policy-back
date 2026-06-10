This project is a Policy-to-Production AI Compliance Platform (Healthcare vertical).

Purpose:
Build an enterprise-grade policy versioning and ingestion system that supports:
- Immutable policy versioning
- Azure Blob document storage
- Content and metadata hashing
- Ingestion batches
- Section-level extraction
- Parse status lifecycle
- Future RAG integration
- Audit-grade traceability

Stack:
- FastAPI
- Azure Blob Storage
- PostgreSQL
- Azure Storage Queue (for background processing)
- SQLAlchemy ORM
- Pydantic models
- Alembic for migrations

Retrieval & Answering Architecture (Phase 2.5)

Flow:
- User Query
	- Input arrives at `POST /v1/ask` with tenant, user context, and scope.
- Azure OpenAI embedding
	- Query text is embedded using configured Azure OpenAI deployment.
	- Embedding is used for semantic nearest-neighbor retrieval.
- pgvector similarity search
	- Vector search runs against `policy_embeddings` in PostgreSQL/pgvector.
	- Returns high semantic matches even when wording differs from policy text.
- postgres FTS search
	- PostgreSQL full-text search runs in parallel to catch lexical/keyword matches.
	- Helps with exact terms, acronyms, and compliance-specific phrasing.
- hybrid merge
	- Vector and FTS results are merged into a single candidate set.
	- De-duplication and score normalization keep recall high without noisy repeats.
- department-first ranking
	- Ranker prioritizes evidence from policies aligned to the user department.
	- Current/effective policy scope is preserved before final selection.
- answer + citations
	- LLM answer is generated from top-ranked evidence chunks.
	- Response includes citation handles and audit traceability (`audit_id`, evidence list).

Compact pipeline view:
- User Query
	↓
- Azure OpenAI embedding
	↓
- pgvector similarity search
	├── postgres FTS search
	↓
- hybrid merge
	↓
- department-first ranking
	↓
- answer + citations

Design Requirements:
- Policy versions are immutable
- Only one current version per policy
- Content hash + metadata hash determine uniqueness
- Strict API contracts
- Clean separation of API layer and worker layer
- No business logic in controllers; use service layer
- Enterprise-grade logging and error handling

Running the API:
- Back-compat entrypoint (still works): `uvicorn app:app --host 0.0.0.0 --port 8000`
- New canonical entrypoint: `uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`

Local dev (Phase 1 end-to-end): Postgres + Azurite

Prereqs:
- Docker Desktop
- Python venv with deps installed: `python -m pip install -r requirements.txt`

Notes:
- Docker Postgres binds to host port `5433` (to avoid conflicts with a locally installed Postgres on `5432`).
- Azurite may not support the newest Azure Storage service API version headers; `.env` pins `AZURE_STORAGE_API_VERSION` for compatibility.

1) Start infra:
- Infra only (Postgres + Azurite): `docker compose up -d postgres azurite`

Dockerized API + Worker (optional)

This repo can also run the API + worker in Docker (Swagger still works from your host browser):

1) Build + start everything:
- `docker compose up -d --build`

2) Apply DB schema (one-time / after migrations):
- `docker compose run --rm api alembic upgrade head`

3) Seed tenant + initialize storage (run from host as usual):
- `python scripts/seed_local_db.py`
- `python scripts/init_local_storage.py`

Swagger UI:
- `http://localhost:8000/docs`

2) Apply DB schema:
- `alembic upgrade head`

2.1) Seed a local tenant (required by FK constraints):
- `python scripts/seed_local_db.py`

3) Initialize local storage objects (creates containers + queue if missing):
- `python scripts/init_local_storage.py`

4) Run API + Worker:
- API (VS Code launch config or CLI): `uvicorn app:app --reload --env-file .env`
- Worker (back-compat): `python -m worker.policy_processor`
- Worker (new canonical): `python -m apps.worker.main`

Phase 2 endpoints:
- `POST /v1/ask`
- `GET /v1/audit/{audit_id}`
- `POST /v1/audit/{audit_id}/replay`

Phase 1 demo flow (Swagger UI or Postman)

All requests below use a tenant UUID. For local demos, you can reuse any UUID (example shown):
- `tenant_id=00000000-0000-0000-0000-000000000001` (created by `scripts/seed_local_db.py`)

1) Create an ingestion batch:
- `POST /v1/ingest/batches`
	- body: `{ "tenant_id": "00000000-0000-0000-0000-000000000001" }`

2) Get an upload SAS URL:
- `POST /v1/ingest/batches/{batch_id}/upload-urls`
	- body: `{ "container_name": "policy-raw", "blob_path": "documents/sample/v1.pdf", "content_type": "application/pdf" }`

3) Upload the file using the SAS URL (PowerShell example):
- `Invoke-WebRequest -Uri <upload_sas_url> -Method Put -InFile .\your.pdf -Headers @{"x-ms-blob-type"="BlockBlob";"Content-Type"="application/pdf"}`

4) Register the uploaded blob:
- `POST /v1/ingest/batches/{batch_id}/register`
	- body:
		`{
			"container_name": "policy-raw",
			"blob_path": "documents/sample/v1.pdf",
			"policy_external_id": "DOC_SET_A",
			"policy_name": "Sample Governance Document",
			"version_label": "v1",
			"metadata": {"department":"operations","sensitivity":"internal","type":"general"}
		}`

5) Watch status & results:
- `GET /v1/ingest/batches/{batch_id}` (shows status)
- `GET /v1/policies?tenant_id=...` (policy catalog)
- `GET /v1/policies/{policy_id}/versions?tenant_id=...` (versions, `is_current`, hashes, raw/extracted blob URIs, lineage)
- `GET /v1/policy-versions/{policy_version_id}/sections?tenant_id=...&limit=20` (top sections)

Swagger / OpenAPI:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Export a shareable schema file: `python scripts/export_openapi.py` (writes `openapi.json`)

Logging:
- Logs are JSON lines to stdout (Azure App Service friendly).
- Each request gets `X-Request-ID` (generated) and `X-Correlation-ID` (propagated from incoming headers or falls back to request id).