"""Q6: ingress & API hardening bundle.

Builds small FastAPI apps around the middleware rather than the full
create_app(), so these run with no database, blob store or queue.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.config import ApiConfig
from apps.api.exception_handlers import register_exception_handlers
from apps.api.hardening import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from packages.core.dtos import AskRequest
from packages.core.errors import DomainError, NotImplementedFeature
from packages.core.middleware import RequestContextMiddleware


def _app(
    *,
    security: bool | None = None,
    body_limit: int | None = None,
    rate_limit: tuple[int, int] | None = None,
) -> FastAPI:
    app = FastAPI()

    if security is not None:
        app.add_middleware(SecurityHeadersMiddleware, hsts=security)
    if body_limit is not None:
        app.add_middleware(BodySizeLimitMiddleware, max_bytes=body_limit)
    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=rate_limit[0],
            window_seconds=rate_limit[1],
        )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        return payload

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected internal failure")

    @app.get("/domain")
    def domain() -> None:
        raise DomainError(code="POLICY_INVALID", message="Policy is invalid")

    @app.get("/unimplemented")
    def unimplemented() -> None:
        raise NotImplementedFeature(message="Not built yet")

    @app.get("/teapot")
    def teapot() -> None:
        raise HTTPException(status_code=418, detail="I am a teapot")

    return app


# --- body size cap ------------------------------------------------------


def test_oversized_declared_body_is_rejected() -> None:
    client = TestClient(_app(body_limit=1024))

    response = client.post("/echo", content=b"x" * 5000)

    assert response.status_code == 413
    body = response.json()
    assert body["code"] == "REQUEST_TOO_LARGE"
    assert "correlation_id" in body


def test_body_within_the_cap_passes() -> None:
    client = TestClient(_app(body_limit=1024 * 1024))

    response = client.post("/echo", json={"hello": "world"})

    assert response.status_code == 200
    assert response.json() == {"hello": "world"}


def test_streamed_body_without_content_length_is_still_capped() -> None:
    """A chunked upload must not slip past the Content-Length check.

    Driven at the ASGI layer because TestClient buffers a generator body and
    then sets Content-Length, which the cheap check would catch first.
    """
    import anyio

    app = _app(body_limit=1024)

    sent: list[dict[str, object]] = []
    remaining = [b"x" * 500] * 10

    async def receive() -> dict[str, object]:
        # 500-byte chunks, none declared up front; terminates after the last.
        if remaining:
            chunk = remaining.pop()
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": bool(remaining),
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/echo",
        "raw_path": b"/echo",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 1234),
        "server": ("test", 80),
    }

    anyio.run(app, scope, receive, send)  # type: ignore[arg-type]  # raw ASGI driver

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413


# --- rate limiting ------------------------------------------------------


def test_rate_limit_blocks_after_the_budget() -> None:
    client = TestClient(_app(rate_limit=(3, 60)))

    statuses = [client.post("/echo", json={}).status_code for _ in range(5)]

    assert statuses[:3] == [200, 200, 200]
    assert statuses[3:] == [429, 429]


def test_rate_limited_response_carries_the_envelope_and_retry_after() -> None:
    client = TestClient(_app(rate_limit=(1, 60)))
    client.post("/echo", json={})

    response = client.post("/echo", json={})

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "60"


def test_health_is_exempt_from_rate_limiting() -> None:
    client = TestClient(_app(rate_limit=(1, 60)))

    statuses = [client.get("/health").status_code for _ in range(5)]

    assert statuses == [200] * 5


# --- security headers ---------------------------------------------------


def test_security_headers_are_present() -> None:
    client = TestClient(_app(security=False))

    headers = client.get("/health").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "Permissions-Policy" in headers
    assert "Strict-Transport-Security" not in headers


def test_hsts_is_added_when_enabled() -> None:
    client = TestClient(_app(security=True))

    headers = client.get("/health").headers

    assert "max-age=31536000" in headers["Strict-Transport-Security"]


# --- uniform error envelope ---------------------------------------------


def test_unhandled_error_returns_envelope_without_leaking_internals() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["message"] == "Unexpected error"
    assert "unexpected internal failure" not in response.text
    assert "correlation_id" in body


def test_domain_error_maps_to_400_envelope() -> None:
    client = TestClient(_app())

    response = client.get("/domain")

    assert response.status_code == 400
    assert response.json()["code"] == "POLICY_INVALID"


def test_not_implemented_feature_maps_to_501() -> None:
    client = TestClient(_app())

    response = client.get("/unimplemented")

    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


def test_http_exception_keeps_its_status_in_the_envelope() -> None:
    client = TestClient(_app())

    response = client.get("/teapot")

    assert response.status_code == 418
    assert response.json()["code"] == "HTTP_418"


def test_validation_error_uses_the_envelope() -> None:
    client = TestClient(_app())

    response = client.post(
        "/echo", content=b"not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "errors" in body["detail"]


# --- bounded question ---------------------------------------------------


def test_ask_question_length_is_bounded() -> None:
    from uuid import uuid4

    with pytest.raises(ValidationError):
        AskRequest(tenant_id=uuid4(), question="x" * 4001)


def test_ask_question_rejects_empty() -> None:
    from uuid import uuid4

    with pytest.raises(ValidationError):
        AskRequest(tenant_id=uuid4(), question="")


def test_ask_question_accepts_a_normal_question() -> None:
    from uuid import uuid4

    request = AskRequest(tenant_id=uuid4(), question="What is the retention period?")

    assert request.question.startswith("What")


# --- config defaults ----------------------------------------------------


def test_docs_default_off_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ENABLE_DOCS", raising=False)

    assert ApiConfig.from_env().enable_docs is False


def test_docs_default_on_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("ENABLE_DOCS", raising=False)

    assert ApiConfig.from_env().enable_docs is True


def test_docs_can_be_force_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENABLE_DOCS", "true")

    assert ApiConfig.from_env().enable_docs is True


def test_hsts_defaults_on_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("HSTS_ENABLED", raising=False)

    config = ApiConfig.from_env()
    assert config.hsts_enabled is True
    assert config.is_local is False


def test_body_limits_are_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BODY_BYTES", "999999999999")

    assert ApiConfig.from_env().max_body_bytes == 500 * 1024 * 1024


def test_invalid_int_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "not-a-number")

    assert ApiConfig.from_env().rate_limit_requests == 120
