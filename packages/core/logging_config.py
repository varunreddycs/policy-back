from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from packages.core.request_context import get_correlation_id, get_request_id


class RequestContextFilter(logging.Filter):
	"""Injects request-scoped IDs into every LogRecord."""

	def filter(self, record: logging.LogRecord) -> bool:
		record.correlation_id = get_correlation_id() or None
		record.request_id = get_request_id() or None
		return True


class JsonLogFormatter(logging.Formatter):
	"""JSON log formatter compatible with Azure App Service (stdout JSON lines)."""

	def __init__(self, *, service_name: str, environment: str) -> None:
		super().__init__()
		self._service_name = service_name
		self._environment = environment

	def format(self, record: logging.LogRecord) -> str:
		payload: Dict[str, Any] = {
			"timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
			"level": record.levelname,
			"logger": record.name,
			"message": record.getMessage(),
			"service": self._service_name,
			"environment": self._environment,
			"correlation_id": getattr(record, "correlation_id", None),
			"request_id": getattr(record, "request_id", None),
		}

		payload["code"] = {
			"file": record.pathname,
			"line": record.lineno,
			"function": record.funcName,
		}

		for key, value in record.__dict__.items():
			if key.startswith("_"):
				continue
			if key in {
				"name",
				"msg",
				"args",
				"levelname",
				"levelno",
				"pathname",
				"filename",
				"module",
				"exc_info",
				"exc_text",
				"stack_info",
				"lineno",
				"funcName",
				"created",
				"msecs",
				"relativeCreated",
				"thread",
				"threadName",
				"processName",
				"process",
				"correlation_id",
				"request_id",
			}:
				continue
			if key in payload:
				continue
			payload[key] = value

		if record.exc_info:
			exc_type, exc, tb = record.exc_info
			payload["exception"] = {
				"type": getattr(exc_type, "__name__", str(exc_type)),
				"message": str(exc),
				"stacktrace": "".join(traceback.format_exception(exc_type, exc, tb)),
			}
		elif record.stack_info:
			payload["stack"] = record.stack_info

		return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _env(name: str, default: str) -> str:
	value = os.getenv(name)
	return value.strip() if value and value.strip() else default


def configure_logging(
	*,
	service_name: str = "policy-back",
	environment: Optional[str] = None,
	level: Optional[str] = None,
) -> None:
	env = environment or _env("ENVIRONMENT", _env("APP_ENV", "local"))
	level_name = (level or _env("LOG_LEVEL", "INFO")).upper()
	log_level = getattr(logging, level_name, logging.INFO)

	handler = logging.StreamHandler(stream=sys.stdout)
	handler.setFormatter(JsonLogFormatter(service_name=service_name, environment=env))
	handler.addFilter(RequestContextFilter())

	root = logging.getLogger()
	root.handlers.clear()
	root.addHandler(handler)
	root.setLevel(log_level)

	for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
		logger_obj = logging.getLogger(name)
		logger_obj.handlers.clear()
		logger_obj.propagate = True
		logger_obj.setLevel(log_level)
