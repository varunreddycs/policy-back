from __future__ import annotations

import logging
import os
from typing import Optional

import requests


logger = logging.getLogger(__name__)

REFUSAL_PHRASE = "Insufficient evidence in available policy sections."


class LlmClient:
    """Azure OpenAI Chat Completions client.

    Gracefully degrades: if AZURE_OPENAI_CHAT_DEPLOYMENT is not set, ``available``
    returns False and callers should fall back to excerpt-based answers.
    """

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
        deployment: Optional[str] = None,
    ) -> None:
        self._endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self._api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self._api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
        self._deployment = deployment or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")

    @property
    def available(self) -> bool:
        return bool(self._endpoint and self._api_key and self._deployment)

    def complete(self, system_prompt: str, user_message: str) -> str:
        """Call Azure OpenAI chat completions. Raises RuntimeError on failure."""
        if not self.available:
            raise RuntimeError(
                "LLM not configured — set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "and AZURE_OPENAI_CHAT_DEPLOYMENT"
            )

        url = (
            f"{self._endpoint.rstrip('/')}/openai/deployments/{self._deployment}/chat/completions"
        )
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        resp = requests.post(
            url,
            params={"api-version": self._api_version},
            json=body,
            headers=headers,
            timeout=60,
        )

        if resp.status_code >= 400:
            logger.error(
                "llm.request.failed",
                extra={"status": resp.status_code, "body": resp.text[:300]},
            )
            raise RuntimeError(f"LLM request failed ({resp.status_code}): {resp.text[:200]}")

        return resp.json()["choices"][0]["message"]["content"]
