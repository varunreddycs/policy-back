# Ohio Docs Ingestor

Scalable ingestion tool for external Ohio policy libraries into the existing Policy-to-Production backend using **existing ingestion endpoints only**.

## Supported agencies

- DAS (default index pre-configured): `https://das.ohio.gov/employee-relations/policies`
- JFS (set `JFS_INDEX_URL` in `.env` when available)

## Uses existing backend endpoints

- `POST /v1/ingest/batches`
- `POST /v1/ingest/batches/{batch_id}/upload-urls?tenant_id=...`
- `POST /v1/ingest/batches/{batch_id}/register?tenant_id=...`
- `GET /v1/ingest/batches/{batch_id}?tenant_id=...`

No backend API contracts are changed.

## Setup

From `policy-back/tools/ohio_docs_ingestor`:

1. Copy env template:
   - `copy .env.example .env` (Windows)
2. Adjust values in `.env`.
3. Install package (editable):
   - `python -m pip install -e .`

## Commands

- Discover only:
  - `python -m ohio_docs_ingestor discover --agency DAS --max-docs 50`
- Ingest from discovered manifest:
  - `python -m ohio_docs_ingestor ingest --agency DAS --max-docs 50`
- Full pipeline (discover + ingest + wait + embeddings):
  - `python -m ohio_docs_ingestor run --agency DAS --max-docs 0`

## Recommended run strategy

1) Pilot ingest first (10 docs)

- `python -m ohio_docs_ingestor discover --agency DAS --max-docs 10`
- `python -m ohio_docs_ingestor run --agency DAS --max-docs 10`

2) Then full run (for example 75 docs)

- Keep guardrails conservative:
  - `UPLOAD_CONCURRENCY=2`
  - `RATE_LIMIT_SECONDS=1` or `2`
  - `MAX_MB=25` (increase to `40` only if needed)

## Built-in protections for irregular doc sizes

- HEAD pre-check for `Content-Length` to skip oversized files early.
- Streamed GET download (no full-file in-memory buffering).
- PDF content sniffing to catch HTML/error pages returned from PDF links.
- Retry/backoff + configurable connect/read timeouts.
- Resume state under `out/state/{agency}-ingest-state.json` so reruns continue safely.

## What the tool does

1. Crawl index page and discover PDF/HTML policy links.
2. Normalize and dedupe links.
3. Save discovery manifest to `out/manifests/{agency}-discovered.json`.
4. Download docs to `out/downloads/{agency}/`, compute sha256, and cache in `out/state/download_index.json`.
5. Create ingest batch, request SAS upload URL, upload blob, register document with metadata.
6. Poll batch status and DB parse-status counts (`registered`, `processing`, `ready`, `failed`).
7. Trigger embeddings backfill with `python -m apps.worker.jobs.embed_backfill --tenant-id ... --only-current`.
8. Write run report to `out/reports/{run_id}-{agency}-report.json`.

## Output structure

```
out/
  manifests/
    das-discovered.json
    jfs-discovered.json
  downloads/
    das/
      <external_id>.pdf|.html
    jfs/
      <external_id>.pdf|.html
  reports/
    <run_id>-das-report.json
    <run_id>-jfs-report.json
  state/
    download_index.json
```

## Metadata shape used at register

```json
{
  "source_system": "ohio-docs",
  "agency": "DAS",
  "policy_source_type": "external",
  "jurisdiction": "ohio",
  "source_url": "...",
  "content_sha256": "...",
  "policy_type": "external_policy",
  "department_scope": "all",
  "authority_level": 50
}
```

This supports future ranking/filtering such as preferring internal over external and filtering by agency.
