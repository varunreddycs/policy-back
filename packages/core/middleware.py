from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from packages.core.request_context import clear_request_context, set_correlation_id, set_request_id


logger = logging.getLogger("app.http")


def _pick_header(request: Request, names: list[str]) -> Optional[str]:
	for name in names:
		value = request.headers.get(name)
		if value:
			return value.strip()
	return None


class RequestContextMiddleware(BaseHTTPMiddleware):
	"""Populates correlation_id and request_id for structured logging."""

	async def dispatch(self, request: Request, call_next: Callable) -> Response:
		request_id = str(uuid.uuid4())
		incoming_correlation = _pick_header(
			request,
			[
				"x-correlation-id",
				"x-ms-client-request-id",
				"x-request-id",
			],
		)
		correlation_id = incoming_correlation or request_id

		set_request_id(request_id)
		set_correlation_id(correlation_id)

		start = time.perf_counter()
		response: Optional[Response] = None
		try:
			response = await call_next(request)
			return response
		except Exception:
			logger.exception(
				"http.request.failed",
				extra={
					"http": {
						"method": request.method,
						"path": request.url.path,
						"query": request.url.query or None,
					},
				},
			)
			raise
		finally:
			duration_ms = int((time.perf_counter() - start) * 1000)
			status_code = response.status_code if response is not None else 500

			if response is not None:
				response.headers.setdefault("X-Request-ID", request_id)
				response.headers.setdefault("X-Correlation-ID", correlation_id)

			logger.info(
				"http.request.completed",
				extra={
					"http": {
						"method": request.method,
						"path": request.url.path,
						"query": request.url.query or None,
						"scheme": request.url.scheme,
						"host": request.headers.get("host"),
						"status_code": status_code,
						"duration_ms": duration_ms,
					},
					"client": {
						"ip": request.client.host if request.client else None,
						"port": request.client.port if request.client else None,
						"user_agent": request.headers.get("user-agent"),
					},
				},
			)

			clear_request_context()
