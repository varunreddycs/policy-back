from __future__ import annotations

import os
from dataclasses import dataclass, field

_DEFAULT_CORS_ORIGINS = (
    "https://platform.mistrv.com",
    "https://ambitious-moss-03cc3bd0f.1.azurestaticapps.net",
    "http://localhost:5173",
    "http://localhost:4280",
)


@dataclass(frozen=True)
class ApiConfig:
    environment: str
    enable_docs: bool
    cors_allow_origins: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_CORS_ORIGINS)

    @staticmethod
    def from_env() -> "ApiConfig":
        env = os.getenv("ENVIRONMENT", "local")
        enable_docs = os.getenv("ENABLE_DOCS", "true").lower() in {"1", "true", "yes", "y"}
        raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
        origins = tuple(o.strip() for o in raw.split(",") if o.strip()) or _DEFAULT_CORS_ORIGINS
        return ApiConfig(environment=env, enable_docs=enable_docs, cors_allow_origins=origins)
