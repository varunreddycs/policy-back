from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiConfig:
    environment: str
    enable_docs: bool

    @staticmethod
    def from_env() -> "ApiConfig":
        env = os.getenv("ENVIRONMENT", "local")
        enable_docs = os.getenv("ENABLE_DOCS", "true").lower() in {"1", "true", "yes", "y"}
        return ApiConfig(environment=env, enable_docs=enable_docs)
