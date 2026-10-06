from __future__ import annotations

import os
from dataclasses import dataclass, field

_DEFAULT_CORS_ORIGINS = (
    "https://platform.mistrv.com",
    "https://ambitious-moss-03cc3bd0f.1.azurestaticapps.net",
    "http://localhost:5173",
    "http://localhost:4280",
)

_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "development", "test"})
_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUTHY


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(value, max_value))


@dataclass(frozen=True)
class ApiConfig:
    environment: str
    enable_docs: bool
    cors_allow_origins: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_CORS_ORIGINS
    )
    max_body_bytes: int = 25 * 1024 * 1024
    max_upload_bytes: int = 25 * 1024 * 1024
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_enabled: bool = True
    hsts_enabled: bool = False

    @property
    def is_local(self) -> bool:
        return self.environment.strip().lower() in _LOCAL_ENVIRONMENTS

    @staticmethod
    def from_env() -> ApiConfig:
        env = os.getenv("ENVIRONMENT", "local")
        is_local = env.strip().lower() in _LOCAL_ENVIRONMENTS

        # Q6: interactive docs expose the full API surface, so they default OFF
        # outside local/dev and must be turned on deliberately.
        enable_docs = _env_bool("ENABLE_DOCS", is_local)

        raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
        origins = (
            tuple(o.strip() for o in raw.split(",") if o.strip())
            or _DEFAULT_CORS_ORIGINS
        )

        max_body = _env_int(
            "MAX_BODY_BYTES",
            25 * 1024 * 1024,
            min_value=1024,
            max_value=500 * 1024 * 1024,
        )

        return ApiConfig(
            environment=env,
            enable_docs=enable_docs,
            cors_allow_origins=origins,
            max_body_bytes=max_body,
            max_upload_bytes=_env_int(
                "MAX_UPLOAD_BYTES",
                max_body,
                min_value=1024,
                max_value=500 * 1024 * 1024,
            ),
            rate_limit_requests=_env_int(
                "RATE_LIMIT_REQUESTS", 120, min_value=1, max_value=100_000
            ),
            rate_limit_window_seconds=_env_int(
                "RATE_LIMIT_WINDOW_SECONDS", 60, min_value=1, max_value=3600
            ),
            rate_limit_enabled=_env_bool("RATE_LIMIT_ENABLED", True),
            hsts_enabled=_env_bool("HSTS_ENABLED", not is_local),
        )
