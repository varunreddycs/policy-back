"""Backward-compatible FastAPI entrypoint.

The canonical API entrypoint now lives at `apps/api/main.py`.
"""

from apps.api.main import app, create_app

