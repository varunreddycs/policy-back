# Local File Ingest

`run_local_ingest.py` wires local `.txt` / `.pdf` files into the existing Policy-to-Production ingestion APIs.

It uses only existing endpoints:

- `POST /v1/ingest/batches`
- `POST /v1/ingest/batches/{batch_id}/upload-urls?tenant_id=...`
- `POST /v1/ingest/batches/{batch_id}/register?tenant_id=...`
- `GET /v1/ingest/batches/{batch_id}?tenant_id=...`

## Run

From repo root (`policy-back`):

```bash
python tools/local_file_ingest/run_local_ingest.py \
  --input-dir tools/NoteBooks/out/das_policies/txt \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --api-base-url http://localhost:8000 \
  --source-system ohio-docs \
  --agency DAS \
  --jurisdiction ohio \
  --department-scope all \
  --authority-level 50 \
  --policy-type external_policy \
  --only-current true \
  --max-files 0 \
  --rate-limit-seconds 0.2 \
  --container-name policies \
  --blob-prefix external/das/
```

Dry-run:

```bash
python tools/local_file_ingest/run_local_ingest.py \
  --input-dir tools/NoteBooks/out/das_policies \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --dry-run
```

## Mapping Rules Implemented

- `policy_external_id`:
  - `external_id = sha1(relative_path_without_extension)[:12]`
  - `policy_external_id = "{source_system}-{agency}-{external_id}"`
- `policy_name`: filename without extension, title-cased.
- `version_label`: unique per run and file hash: `v1-{runStamp}-{sha256[:8]}`.
- `effective_date`: parsed from filename `YYYY-MM-DD`, else `null`.
- `title`: same as `policy_name`.
- `blob_path`: `{blob_prefix}{policy_external_id}/{runStamp}-{filename}`.

Metadata includes:

- `source_system`
- `agency`
- `jurisdiction`
- `policy_source_type` = `external`
- `source_file` (relative path)
- `source_url` (if `<file>.json` sidecar contains `source_url`)
- `authority_level`
- `department_scope`
- `policy_type`
- `file_sha256`
- `content_type`

## Output Report

A JSON report is written to:

- `tools/local_file_ingest/out/report-{runStamp}.json`

Includes per-file status, register response, policy/version IDs, and poll summary.

## Common Issues

- `No policies created`:
  - Ensure upload succeeded and register is called for every file.
  - Check `tenant_id` is included in query string for `upload-urls` and `register`.
  - Verify `container_name` exists in blob storage.
- `409 conflict` on register:
  - Logged and ingestion continues.
  - Check `policy_external_id` and `version_label` behavior.
- `SAS upload failures`:
  - Confirm local Azurite/container is running and accessible.
- `Batch never reaches ready`:
  - Check worker/extraction pipeline health and backend logs.

## Suggested Next Step

After successful ingestion:

```bash
python -m apps.worker.jobs.embed_backfill --tenant-id <TENANT_ID> --only-current
```
