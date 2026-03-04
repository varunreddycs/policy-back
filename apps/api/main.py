from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

    web_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    web_assets = web_dist / "assets"

    if web_dist.exists():
        if web_assets.exists():
            app.mount("/assets", StaticFiles(directory=str(web_assets)), name="web-assets")

        @app.get("/", include_in_schema=False)
        def serve_web_index() -> FileResponse:
            return FileResponse(web_dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def serve_web_spa(full_path: str) -> FileResponse:
            requested = web_dist / full_path
            if requested.is_file():
                return FileResponse(requested)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app()

