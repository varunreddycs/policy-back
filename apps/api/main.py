"""API entrypoint (Phase 2 scaffold).

Keeps Phase-1 layout working while providing a stable import path for uvicorn:
`uvicorn apps.api.main:app`.

Currently re-exports the existing Phase-1 FastAPI app from the repo root.
"""

from app import app  # noqa: F401
