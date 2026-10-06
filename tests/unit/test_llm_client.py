"""Q2: the LLM client must retry transient faults and never pass off a truncated answer."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from packages.llm.client import (
    LlmClient,
    LlmError,
    LlmRetryConfig,
    LlmTruncatedError,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _ok_payload(
    content: str = "AC-2 requires account review.", finish_reason: str = "stop"
) -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 42},
    }


def _client(**kwargs: Any) -> LlmClient:
    defaults: dict[str, Any] = {
        "endpoint": "https://stub.openai.azure.com",
        "api_key": "stub-key",
        "deployment": "stub-deployment",
        # zero backoff keeps the retry tests instant
        "retry": LlmRetryConfig(max_retries=2, base_backoff_ms=0),
    }
    defaults.update(kwargs)
    return LlmClient(**defaults)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never actually sleep in unit tests."""
    monkeypatch.setattr("packages.llm.client.time.sleep", lambda _seconds: None)


def test_unavailable_client_raises_rather_than_calling_out() -> None:
    client = LlmClient(endpoint="", api_key="", deployment="")
    assert client.available is False
    with pytest.raises(LlmError, match="not configured"):
        client.complete_detailed("sys", "user")


def test_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append(1)
        if len(calls) < 3:
            return _FakeResponse(429, headers={"Retry-After": "0"})
        return _FakeResponse(200, _ok_payload())

    monkeypatch.setattr("packages.llm.client.requests.post", fake_post)

    result = _client().complete_detailed("sys", "user")

    assert len(calls) == 3
    assert result.attempts == 3
    assert result.content == "AC-2 requires account review."
    assert result.completion_tokens == 42


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses_exhaust_then_raise(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls: list[int] = []

    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(status, text="upstream busy")

    monkeypatch.setattr("packages.llm.client.requests.post", fake_post)

    with pytest.raises(LlmError):
        _client().complete_detailed("sys", "user")

    # max_retries=2 -> 3 total attempts
    assert len(calls) == 3


def test_400_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(400, text="bad request")

    monkeypatch.setattr("packages.llm.client.requests.post", fake_post)

    with pytest.raises(LlmError, match="400"):
        _client().complete_detailed("sys", "user")

    assert len(calls) == 1


def test_transport_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        calls.append(1)
        if len(calls) < 2:
            raise requests.ConnectionError("connection reset")
        return _FakeResponse(200, _ok_payload())

    monkeypatch.setattr("packages.llm.client.requests.post", fake_post)

    result = _client().complete_detailed("sys", "user")

    assert len(calls) == 2
    assert result.attempts == 2


def test_truncated_completion_raises_instead_of_returning_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finish_reason='length' must not be served as a complete compliance answer."""
    monkeypatch.setattr(
        "packages.llm.client.requests.post",
        lambda *a, **k: _FakeResponse(
            200, _ok_payload("Partial ans", finish_reason="length")
        ),
    )

    with pytest.raises(LlmTruncatedError, match="incomplete"):
        _client().complete_detailed("sys", "user")


def test_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.llm.client.requests.post",
        lambda *a, **k: _FakeResponse(200, _ok_payload(content="   ")),
    )

    with pytest.raises(LlmTruncatedError, match="empty content"):
        _client().complete_detailed("sys", "user")


def test_missing_choices_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.llm.client.requests.post",
        lambda *a, **k: _FakeResponse(200, {"choices": []}),
    )

    with pytest.raises(LlmError, match="no choices"):
        _client().complete_detailed("sys", "user")


def test_max_completion_tokens_is_budgeted(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs.get("json") or {})
        return _FakeResponse(200, _ok_payload())

    monkeypatch.setattr("packages.llm.client.requests.post", fake_post)

    _client(max_completion_tokens=256).complete_detailed("sys", "user")

    assert captured["max_completion_tokens"] == 256


def test_complete_wrapper_returns_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.llm.client.requests.post",
        lambda *a, **k: _FakeResponse(200, _ok_payload()),
    )

    assert _client().complete("sys", "user") == "AC-2 requires account review."
