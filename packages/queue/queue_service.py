from __future__ import annotations

import logging
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from packages.queue.queue_publisher import QueuePublisher, QueuePublisherError


logger = logging.getLogger(__name__)


class QueueServiceError(RuntimeError):
	pass


class EnqueueFailedError(QueueServiceError):
	pass


def _optional_env(name: str) -> Optional[str]:
	value = os.getenv(name)
	return value if value else None


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
	raw = os.getenv(name)
	if not raw:
		return default
	try:
		value = int(raw)
	except ValueError as exc:
		raise QueueServiceError(f"{name} must be an integer") from exc
	if value < min_value or value > max_value:
		raise QueueServiceError(f"{name} must be in [{min_value}, {max_value}]")
	return value


@dataclass(frozen=True, slots=True)
class QueueServiceConfig:
	correlation_id: Optional[str]
	max_retries: int
	base_backoff_ms: int

	@staticmethod
	def from_env() -> "QueueServiceConfig":
		correlation_id = _optional_env("CORRELATION_ID") or _optional_env("AZURE_CORRELATION_ID")
		max_retries = _env_int("AZURE_QUEUE_PUBLISH_MAX_RETRIES", 3, min_value=0, max_value=10)
		base_backoff_ms = _env_int("AZURE_QUEUE_PUBLISH_BASE_BACKOFF_MS", 200, min_value=0, max_value=60_000)
		return QueueServiceConfig(
			correlation_id=correlation_id,
			max_retries=max_retries,
			base_backoff_ms=base_backoff_ms,
		)


class QueueService:
	"""Domain-focused queue wrapper."""

	def __init__(
		self,
		*,
		publisher: QueuePublisher,
		config: Optional[QueueServiceConfig] = None,
	) -> None:
		self._publisher = publisher
		self._config = config or QueueServiceConfig.from_env()

	@staticmethod
	def from_env(*, config: Optional[QueueServiceConfig] = None) -> "QueueService":
		publisher = QueuePublisher()
		return QueueService(publisher=publisher, config=config)

	def enqueue_policy_processing(self, policy_version_id: uuid.UUID, *, correlation_id: Optional[str] = None) -> None:
		if not isinstance(policy_version_id, uuid.UUID):
			raise ValueError("policy_version_id must be a UUID")

		effective_correlation_id = correlation_id or self._config.correlation_id

		request_id = f"policy_version:{policy_version_id}"
		payload = {
			"type": "policy.process.requested",
			"request_id": request_id,
			"policy_version_id": str(policy_version_id),
			"correlation_id": effective_correlation_id,
			"created_at": datetime.now(UTC).isoformat(),
		}

		attempts = 0
		last_exc: Optional[Exception] = None

		while attempts <= self._config.max_retries:
			try:
				self._publisher.publish_json(payload)
				logger.info(
					"queue_service.enqueued_policy_processing",
					extra={
						"queue": self._publisher.queue_name,
						"policy_version_id": str(policy_version_id),
						"request_id": request_id,
						"correlation_id": effective_correlation_id,
						"attempt": attempts + 1,
					},
				)
				return
			except QueuePublisherError as exc:
				last_exc = exc
				attempts += 1
				logger.warning(
					"queue_service.enqueue_failed",
					extra={
						"queue": self._publisher.queue_name,
						"policy_version_id": str(policy_version_id),
						"request_id": request_id,
						"correlation_id": effective_correlation_id,
						"attempt": attempts,
						"max_retries": self._config.max_retries,
					},
				)

				if attempts > self._config.max_retries:
					break

				if self._config.base_backoff_ms > 0:
					backoff_ms = self._config.base_backoff_ms * (2 ** (attempts - 1))
					backoff_ms = min(backoff_ms, 30_000)
					jitter_ms = random.randint(0, min(250, backoff_ms))
					time.sleep((backoff_ms + jitter_ms) / 1000.0)

		logger.exception(
			"queue_service.enqueue_giving_up",
			extra={
				"queue": self._publisher.queue_name,
				"policy_version_id": str(policy_version_id),
				"request_id": request_id,
				"correlation_id": effective_correlation_id,
				"attempts": attempts,
			},
		)
		raise EnqueueFailedError("Failed to enqueue policy processing") from last_exc


__all__ = [
	"QueueService",
	"QueueServiceConfig",
	"QueueServiceError",
	"EnqueueFailedError",
]
