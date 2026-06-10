# Backend Summary

Date: 2026-03-04
Location: policy-back (root)

## Stack
- FastAPI API + Python worker
- PostgreSQL + Alembic
- Azure Blob + Queue (Azurite local)
- SQLAlchemy + Pydantic

## Architecture
- API entry: apps/api/main.py (back-compat app.py)
- Worker entry: apps/worker/main.py
- Domain packages under packages/* (db, ingestion, retrieval, rag, governance, queue, storage)

## Core Capabilities
- Policy ingestion batches and registration
- Versioned policies + section extraction
- Ask endpoint + audit retrieval + replay
- Queue-based background extraction worker
- Phase 2.5 semantic retrieval components:
	- Azure OpenAI embedding client
	- `policy_embeddings` pgvector table (HNSW index)
	- pgvector retriever + hybrid retriever merge with pgsql FTS
	- retriever backend selection via `RETRIEVER_BACKEND`

## Docker Status
- Single API image now includes backend + built frontend assets
- API and Worker still run as separate services in docker-compose
- API serves SPA and REST endpoints from same container/port
- Postgres service now uses pgvector-capable image: `pgvector/pgvector:pg16`
- Alembic migration `005_enable_pgvector` enables `CREATE EXTENSION vector`

## Local Endpoints
- API / Swagger: http://localhost:8000/docs
- Console UI: http://localhost:8000/console
- Audit UI: http://localhost:8000/audit
