from __future__ import annotations

import os
import time
from typing import Iterable, List

import requests


RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
BATCH_SIZE = 16


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _chunks(items: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _embed_batch(*, endpoint: str, deployment: str, api_version: str, api_key: str, batch: List[str]) -> List[List[float]]:
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings"
    params = {"api-version": api_version}
    payload = {"input": batch}
    headers = {"api-key": api_key, "Content-Type": "application/json"}

    max_attempts = 5
    for attempt in range(max_attempts):
        response = requests.post(url, params=params, json=payload, headers=headers, timeout=60)
        if response.status_code < 400:
            body = response.json()
            data = body.get("data") or []
            sorted_data = sorted(data, key=lambda item: item.get("index", 0))
            return [item.get("embedding", []) for item in sorted_data]

        if response.status_code not in RETRYABLE_STATUS_CODES or attempt == max_attempts - 1:
            raise RuntimeError(f"Embedding request failed ({response.status_code}): {response.text}")

        sleep_seconds = min(8.0, 0.5 * (2**attempt))
        time.sleep(sleep_seconds)

    raise RuntimeError("Embedding request failed after retries")


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    api_key = _require_env("AZURE_OPENAI_API_KEY")
    api_version = _require_env("AZURE_OPENAI_API_VERSION")
    deployment = _require_env("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")

    vectors: List[List[float]] = []
    for batch in _chunks(texts, BATCH_SIZE):
        vectors.extend(
            _embed_batch(
                endpoint=endpoint,
                deployment=deployment,
                api_version=api_version,
                api_key=api_key,
                batch=batch,
            )
        )
    return vectors
