from __future__ import annotations

from fastapi import FastAPI

from apps.api.config import ApiConfig
from apps.api.logging_config import configure_logging
from apps.api.middleware import RequestContextMiddleware
from apps.api.routers import ask, audit, health, ingest, policies, sections


def create_app() -> FastAPI:
    configure_logging()
    config = ApiConfig.from_env()

    app = FastAPI(
        title="Policy Platform API",
        version="0.2.0",
        docs_url="/docs" if config.enable_docs else None,
        redoc_url="/redoc" if config.enable_docs else None,
        openapi_url="/openapi.json" if config.enable_docs else None,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(policies.router)
    app.include_router(sections.router)
    app.include_router(ask.router)
    app.include_router(audit.router)
    return app


app = create_app()

