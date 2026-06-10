# Endpoint JSON fixtures

This folder stores request/response JSON payloads per endpoint to support lightweight automation-style testing.

## Structure
- `tests/fixtures/endpoints/<endpoint>/...`

Example:
- `tests/fixtures/endpoints/ask/request.json`

## How tests use these
Integration tests under `tests/integration/` can load these JSONs and send them to a running API.

By default, integration tests are skipped unless:
- `RUN_INTEGRATION=1`

Most tests also allow overriding:
- `API_BASE_URL` (default: `http://localhost:8000`)
- `DEFAULT_TENANT_ID` (default: `00000000-0000-0000-0000-000000000001`)
