from __future__ import annotations

from fastapi import FastAPI

from core.logging_config import configure_logging
from core.middleware import RequestContextMiddleware
from routers import ingest_router, policy_router


def create_app() -> FastAPI:
	configure_logging()
	tags_metadata = [
		{
			"name": "Ingestion",
			"description": "Upload + register policies for background extraction.",
		},
		{
			"name": "Policies",
			"description": "Query policies and versions (tenant-scoped).",
		},
	]

	app = FastAPI(
		title="Policy Platform API",
		description=(
			"Enterprise policy ingestion and immutable versioning service. "
			"Provides ingestion batches, blob registration, queue-driven extraction, and audit-friendly traceability."
		),
		version="0.1.0",
		openapi_tags=tags_metadata,
	)
	app.add_middleware(RequestContextMiddleware)
	app.include_router(ingest_router)
	app.include_router(policy_router)
	return app


app = create_app()
