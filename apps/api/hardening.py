"""Ingress hardening: body caps, rate limiting, security headers (Q6).

Enterprise/gov procurement treats request-size caps, rate limiting, uniform
error contracts and security headers as baseline. These are deliberately
dependency-free (no slowapi/redis) so they work in every deployment shape this
repo supports, including a single container with no shared cache.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import (
    HTTP_413_CONTENT_TOO_LARGE,
    HTTP_429_TOO_MANY_REQUESTS,
)

from packages.core.request_context import get_correlation_id

logger = logging.getLogger(__name__)


def error_envelope(
    code: str, message: str, *, detail: dict | None = None
) -> dict[str, object]:
    """The single error shape every API failure returns."""
    body: dict[str, object] = {
        "code": code,
        "message": message,
        "correlation_id": get_correlation_id(),
    }
    if detail:
        body["detail"] = detail
    return body


class BodySizeLimitMiddleware:
    """Reject oversized requests before the route reads them.

    Checks Content-Length first (cheap, and what a well-behaved client sends),
    then counts bytes while streaming so a chunked upload without a declared
    length cannot slip past.

    Deliberately raw ASGI rather than BaseHTTPMiddleware: BaseHTTPMiddleware
    hands the route its own buffered stream, so a ``receive`` wrapper installed
    there is never consulted and the streaming cap silently does nothing.
    """

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        declared = headers.get("content-length")
        if declared:
            try:
                if int(declared) > self._max_bytes:
                    await self._reject(int(declared), send)
                    return
            except ValueError:
                pass

        body_size = 0
        max_bytes = self._max_bytes
        rejected = False

        async def limited_receive():
            nonlocal body_size, rejected
            message = await receive()
            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > max_bytes:
                    rejected = True
                    # Cut the stream off; the route sees an empty terminal
                    # chunk instead of the oversized remainder.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        sent_start = False

        async def guarded_send(message) -> None:
            nonlocal sent_start
            if rejected and not sent_start:
                if message["type"] == "http.response.start":
                    sent_start = True
                    await self._reject(body_size, send)
                return
            if rejected:
                return
            if message["type"] == "http.response.start":
                sent_start = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    async def _reject(self, size: int, send) -> None:
        logger.warning(
            "http.request.too_large",
            extra={"size": size, "limit": self._max_bytes},
        )
        response = JSONResponse(
            status_code=HTTP_413_CONTENT_TOO_LARGE,
            content=error_envelope(
                "REQUEST_TOO_LARGE",
                f"Request body exceeds the {self._max_bytes} byte limit.",
            ),
        )
        await _send_response(response, send)


async def _send_response(response: JSONResponse, send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": response.raw_headers,
        }
    )
    await send({"type": "http.response.body", "body": response.body})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window-per-client rate limit.

    In-process, so each replica enforces its own budget — adequate as a cost
    and abuse guard in front of embeddings/LLM calls, and explicitly not a
    distributed quota. Move to a shared store if exact global limits matter.
    """

    def __init__(
        self,
        app,
        *,
        max_requests: int,
        window_seconds: int,
        exempt_paths: tuple[str, ...] = (
            "/health",
            "/healthz",
            "/docs",
            "/openapi.json",
        ),
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._exempt = exempt_paths
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def _client_key(request: Request) -> str:
        # X-Forwarded-For is set by the ingress; fall back to the socket peer.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _allowed(self, key: str, now: float) -> bool:
        window = self._hits[key]
        cutoff = now - self._window
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max:
            return False
        window.append(now)
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._exempt:
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()

        if not self._allowed(key, now):
            logger.warning(
                "http.request.rate_limited",
                extra={"client": key, "path": request.url.path, "limit": self._max},
            )
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content=error_envelope(
                    "RATE_LIMITED",
                    f"Too many requests; limit is {self._max} per {self._window}s.",
                ),
                headers={"Retry-After": str(self._window)},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Standard hardening headers on every response."""

    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if self._hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
