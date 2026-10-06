from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

REFUSAL_PHRASE = "Insufficient evidence in available policy sections."

# Status codes worth retrying: throttling plus transient gateway/server faults.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_MS = 30_000


class LlmError(RuntimeError):
    """LLM call failed after exhausting retries."""


class LlmTruncatedError(LlmError):
    """The model stopped before finishing (finish_reason='length' or empty content).

    Raised separately so the caller can distinguish "the budget was too small"
    from "the service is down" — a truncated compliance answer must never be
    passed off as complete.
    """


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("llm.config.invalid_int", extra={"setting": name, "raw": raw})
        return default
    return max(min_value, min(value, max_value))


@dataclass(frozen=True, slots=True)
class LlmRetryConfig:
    max_retries: int
    base_backoff_ms: int

    @staticmethod
    def from_env() -> LlmRetryConfig:
        return LlmRetryConfig(
            max_retries=_env_int(
                "AZURE_OPENAI_MAX_RETRIES", 3, min_value=0, max_value=10
            ),
            base_backoff_ms=_env_int(
                "AZURE_OPENAI_BASE_BACKOFF_MS", 500, min_value=0, max_value=60_000
            ),
        )


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """A completed model response plus the metadata needed to trust it."""

    content: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1


class LlmClient:
    """Azure OpenAI Chat Completions client.

    Gracefully degrades: if AZURE_OPENAI_CHAT_DEPLOYMENT is not set, ``available``
    returns False and callers should fall back to excerpt-based answers.

    Retries 429/5xx with capped exponential backoff plus jitter, and refuses to
    return a truncated completion as if it were whole.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        deployment: str | None = None,
        max_completion_tokens: int | None = None,
        retry: LlmRetryConfig | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self._endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self._api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self._api_version = api_version or os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-02-01"
        )
        self._deployment = deployment or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
        self._max_completion_tokens = max_completion_tokens or _env_int(
            "AZURE_OPENAI_MAX_COMPLETION_TOKENS", 1024, min_value=64, max_value=32_000
        )
        self._retry = retry or LlmRetryConfig.from_env()
        self._timeout = timeout_seconds or _env_int(
            "AZURE_OPENAI_TIMEOUT_SECONDS", 60, min_value=5, max_value=600
        )

    @property
    def available(self) -> bool:
        return bool(self._endpoint and self._api_key and self._deployment)

    def _sleep_backoff(self, attempt: int) -> None:
        """Capped exponential backoff with jitter (attempt is 1-based)."""
        if self._retry.base_backoff_ms <= 0:
            return
        backoff_ms = min(
            self._retry.base_backoff_ms * (2 ** (attempt - 1)), _MAX_BACKOFF_MS
        )
        jitter_ms = random.randint(0, min(250, backoff_ms))
        time.sleep((backoff_ms + jitter_ms) / 1000.0)

    @staticmethod
    def _retry_after_seconds(resp: requests.Response) -> float | None:
        """Honour the service's own Retry-After when it sends one."""
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None

    def complete_detailed(self, system_prompt: str, user_message: str) -> LlmCompletion:
        """Call Azure OpenAI chat completions, returning content plus metadata.

        Raises:
            LlmError: not configured, or every attempt failed.
            LlmTruncatedError: the model hit the token budget or returned no content.
        """
        if not self.available:
            raise LlmError(
                "LLM not configured — set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_CHAT_DEPLOYMENT"
            )

        url = f"{self._endpoint.rstrip('/')}/openai/deployments/{self._deployment}/chat/completions"
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        # Newer Azure OpenAI models (gpt-5.x) require ``max_completion_tokens`` and
        # only support the default temperature, so we omit ``temperature`` and ``max_tokens``.
        body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_completion_tokens": self._max_completion_tokens,
        }

        last_error: str | None = None
        total_attempts = self._retry.max_retries + 1

        for attempt in range(1, total_attempts + 1):
            try:
                resp = requests.post(
                    url,
                    params={"api-version": self._api_version},
                    json=body,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = f"transport error: {exc}"
                logger.warning(
                    "llm.request.transport_error",
                    extra={
                        "attempt": attempt,
                        "max_attempts": total_attempts,
                        "error": str(exc),
                    },
                )
                if attempt < total_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise LlmError(
                    f"LLM request failed after {attempt} attempt(s): {last_error}"
                ) from exc

            if resp.status_code in _RETRYABLE_STATUS and attempt < total_attempts:
                last_error = f"HTTP {resp.status_code}"
                retry_after = self._retry_after_seconds(resp)
                logger.warning(
                    "llm.request.retrying",
                    extra={
                        "status": resp.status_code,
                        "attempt": attempt,
                        "max_attempts": total_attempts,
                        "retry_after": retry_after,
                    },
                )
                if retry_after is not None:
                    time.sleep(min(retry_after, _MAX_BACKOFF_MS / 1000.0))
                else:
                    self._sleep_backoff(attempt)
                continue

            if resp.status_code >= 400:
                logger.error(
                    "llm.request.failed",
                    extra={
                        "status": resp.status_code,
                        "body": resp.text[:300],
                        "attempt": attempt,
                    },
                )
                raise LlmError(
                    f"LLM request failed ({resp.status_code}): {resp.text[:200]}"
                )

            return self._parse_completion(resp, attempt)

        raise LlmError(
            f"LLM request failed after {total_attempts} attempt(s): {last_error}"
        )

    def _parse_completion(self, resp: requests.Response, attempt: int) -> LlmCompletion:
        try:
            data = resp.json()
        except ValueError as exc:
            raise LlmError("LLM returned a non-JSON body") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LlmError("LLM response contained no choices")

        choice = choices[0] or {}
        finish_reason = choice.get("finish_reason")
        content = ((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}

        if finish_reason == "length":
            logger.warning(
                "llm.response.truncated",
                extra={
                    "finish_reason": finish_reason,
                    "max_completion_tokens": self._max_completion_tokens,
                    "completion_tokens": usage.get("completion_tokens"),
                },
            )
            raise LlmTruncatedError(
                f"LLM stopped at the {self._max_completion_tokens}-token budget "
                "(finish_reason='length'); the answer would be incomplete"
            )

        if not content:
            logger.warning("llm.response.empty", extra={"finish_reason": finish_reason})
            raise LlmTruncatedError(
                f"LLM returned empty content (finish_reason={finish_reason!r})"
            )

        return LlmCompletion(
            content=content,
            finish_reason=finish_reason,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            attempts=attempt,
        )

    def complete(self, system_prompt: str, user_message: str) -> str:
        """Backward-compatible wrapper returning just the answer text."""
        return self.complete_detailed(system_prompt, user_message).content


__all__ = [
    "REFUSAL_PHRASE",
    "LlmClient",
    "LlmCompletion",
    "LlmError",
    "LlmRetryConfig",
    "LlmTruncatedError",
]
