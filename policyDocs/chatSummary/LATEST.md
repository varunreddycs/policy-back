# Policy Platform backend — status (2026-03-03)

## Goal we just completed
- Repo consolidation so the root contains only: `apps/`, `packages/`, `infra/`, `scripts/`, `tests/`, `policyDocs/` (+ standard root files like `Dockerfile`, `docker-compose.yml`, `alembic.ini`, etc.)
- Migrated legacy top-level code into `apps/` + `packages/`, then deleted the old top-level folders.

## What changed (high level)
- **Legacy folders removed:** `core/`, `db/`, `models/`, `services/`, `repositories/`, `routers/`, `worker/`.
- **Canonical modules now live under:**
  - `packages/db/*` (SQLAlchemy session + ORM + Pydantic contracts)
  - `packages/storage/*` (blob)
  - `packages/queue/*` (queue publisher/service)
  - `packages/ingestion/*` (ingestion service)
  - `apps/api/*` (FastAPI app)
  - `apps/worker/*` (worker loop)

## Key files to know
- API entrypoint: `apps/api/main.py`
- Backward-compat FastAPI import for Docker/uvicorn: `app.py` (`uvicorn app:app`)
- Worker entrypoint: `apps/worker/main.py`
- Worker processing loop: `apps/worker/policy_processor.py`
- Alembic env targets metadata from: `packages/db/base.py`

## Fixes applied during verification
- Fixed Docker API startup **circular import**: removed re-export loop in `apps/api/main.py` (API container now starts).
- Updated Docker worker command in `docker-compose.yml` to run `python -m apps.worker.main`.
- Fixed worker-in-docker connectivity: worker now prefers `AZURE_STORAGE_QUEUE_ACCOUNT_URL_INTERNAL` (so it uses `http://azurite:10001/...` inside the compose network).
- Ran Alembic migrations in docker Postgres to ensure Phase 2 columns/tables exist:
  - `003_audit_logs`
  - `004_policy_ranking_fields`

## Tests
- Added minimal real unit tests + integration tests that are **skipped by default** (they require services).
- Current pytest result: **7 passed, 3 skipped**.
- `pytest.ini` added to register the `integration` marker.
- `requirements-dev.txt` added so `pytest` can be installed consistently.

## Demo verification (Phase 1)
- Phase 1 demo script ran successfully end-to-end:
  - `scripts/demo_phase1.ps1`
  - It created an ingestion batch, generated SAS upload URL, uploaded a demo policy, registered it, worker extracted it, API polled to `parse_status=ready`, and fetched sections.

## How to run (quick)
1) Start stack:
	- `docker compose up -d --build`
2) Apply migrations:
	- `docker compose exec -T api alembic upgrade head`
3) Run Phase 1 demo:
	- `powershell -ExecutionPolicy Bypass -File .\\scripts\\demo_phase1.ps1`
4) Run tests locally:
	- `pip install -r requirements-dev.txt`
	- `python -m pytest -q`

## Current state / open notes
- Integration tests are intentionally lightweight (import-smoke) unless you set `RUN_INTEGRATION=1` and wire them to the running stack.
- Worker log may include earlier schema errors if you look at full history; after migrations it should poll cleanly.
