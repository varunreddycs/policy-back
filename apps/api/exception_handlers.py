"""Global exception handlers producing one uniform error envelope (Q6).

Every failure — domain error, validation error, HTTPException, or an unhandled
crash — leaves the API as {code, message, correlation_id}, so clients can parse
errors without special-casing, and every error is traceable back to a log line.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_501_NOT_IMPLEMENTED,
)

from apps.api.hardening import error_envelope
from packages.core.errors import DomainError, NotImplementedFeature

logger = logging.getLogger(__name__)

# Pydantic puts the offending value in `input`, which for a malformed body is
# raw bytes — not JSON-serializable, and echoing it back would reflect
# arbitrary client input anyway. Drop it and keep the machine-readable parts.
_ERROR_KEYS = ("type", "loc", "msg")


def _safe_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    safe: list[dict[str, object]] = []
    for error in exc.errors():
        if not isinstance(error, dict):
            continue
        entry: dict[str, object] = {}
        for key in _ERROR_KEYS:
            value = error.get(key)
            if value is None:
                continue
            entry[key] = list(value) if isinstance(value, tuple) else str(value)
        safe.append(entry)
    return safe


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotImplementedFeature)
    async def _not_implemented(
        request: Request, exc: NotImplementedFeature
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_501_NOT_IMPLEMENTED,
            content=error_envelope(exc.code, exc.message, detail=exc.detail or None),
        )

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content=error_envelope(exc.code, exc.message, detail=exc.detail or None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_envelope(
                "VALIDATION_ERROR",
                "Request failed validation.",
                detail={"errors": _safe_errors(exc)},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        # Routes that already raise the {code, message, detail} shape keep it.
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=error_envelope(
                    str(detail.get("code")),
                    str(detail.get("message", "Request failed")),
                    detail=detail.get("detail") or None,
                ),
                headers=getattr(exc, "headers", None),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                f"HTTP_{exc.status_code}",
                str(detail) if detail else "Request failed",
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the cause; never leak internals to the client.
        logger.exception(
            "api.unhandled_error",
            extra={"path": request.url.path, "method": request.method},
        )
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_envelope("INTERNAL_ERROR", "Unexpected error"),
        )
