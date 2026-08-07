from __future__ import annotations

import os


def has_embedding_config() -> bool:
    """Return True only when every Azure OpenAI embedding env var is present.

    Mirrors the private ``_has_embedding_config`` check in
    ``packages.retrieval.factory`` so callers outside retrieval (e.g. the
    worker's auto-embed step) can gate embedding cleanly instead of crashing
    when the deployment is unconfigured.
    """
    required = [
        os.getenv("AZURE_OPENAI_ENDPOINT"),
        os.getenv("AZURE_OPENAI_API_KEY"),
        os.getenv("AZURE_OPENAI_API_VERSION"),
        os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
    ]
    return all(bool(item and str(item).strip()) for item in required)
