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

## Docker Status
- Single API image now includes backend + built frontend assets
- API and Worker still run as separate services in docker-compose
- API serves SPA and REST endpoints from same container/port

## Local Endpoints
- API / Swagger: http://localhost:8000/docs
- Console UI: http://localhost:8000/console
- Audit UI: http://localhost:8000/audit
