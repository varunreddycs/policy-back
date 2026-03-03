from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from azure.core.exceptions import AzureError
from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient


logger = logging.getLogger(__name__)


class QueuePublisherError(RuntimeError):
    pass


class QueueConfigurationError(QueuePublisherError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise QueueConfigurationError(f"Missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value if value else None


def _storage_api_version() -> Optional[str]:
    value = os.getenv("AZURE_STORAGE_API_VERSION")
    return value if value else None


@dataclass(frozen=True, slots=True)
class QueuePublisherConfig:
    queue_name: str
    account_url: str
    account_name: str
    account_key: Optional[str]

    @staticmethod
    def from_env() -> "QueuePublisherConfig":
        queue_name = _require_env("AZURE_POLICY_EXTRACTION_QUEUE_NAME")

        # Prefer explicit queue account URL; otherwise infer from AZURE_STORAGE_ACCOUNT_URL/NAME.
        account_url = (
            _optional_env("AZURE_STORAGE_QUEUE_ACCOUNT_URL_INTERNAL")
            or _optional_env("AZURE_STORAGE_QUEUE_ACCOUNT_URL")
        )
        account_name = _optional_env("AZURE_STORAGE_ACCOUNT_NAME")
        storage_account_url = _optional_env("AZURE_STORAGE_ACCOUNT_URL")
        account_key = _optional_env("AZURE_STORAGE_ACCOUNT_KEY")

        if not account_url:
            if account_name:
                account_url = f"https://{account_name}.queue.core.windows.net"
            elif storage_account_url:
                try:
                    host = storage_account_url.split("//", 1)[1].split("/", 1)[0]
                    account_name = host.split(".", 1)[0]
                    account_url = f"https://{account_name}.queue.core.windows.net"
                except Exception as exc:  # pragma: no cover
                    raise QueueConfigurationError(
                        "Unable to infer queue account URL; set AZURE_STORAGE_QUEUE_ACCOUNT_URL."
                    ) from exc
            else:
                raise QueueConfigurationError(
                    "Set AZURE_STORAGE_QUEUE_ACCOUNT_URL or AZURE_STORAGE_ACCOUNT_NAME/AZURE_STORAGE_ACCOUNT_URL."
                )

        if not account_name:
            try:
                host = account_url.split("//", 1)[1].split("/", 1)[0]
                account_name = host.split(".", 1)[0]
            except Exception as exc:  # pragma: no cover
                raise QueueConfigurationError(
                    "Unable to infer account name from AZURE_STORAGE_QUEUE_ACCOUNT_URL; set AZURE_STORAGE_ACCOUNT_NAME."
                ) from exc

        return QueuePublisherConfig(
            queue_name=queue_name,
            account_url=account_url,
            account_name=account_name,
            account_key=account_key,
        )


class QueuePublisher:
    """Publishes messages to an Azure Storage Queue.

    Auth:
    - Shared key via AZURE_STORAGE_ACCOUNT_KEY
    - Entra ID via DefaultAzureCredential otherwise
    """

    def __init__(self, config: Optional[QueuePublisherConfig] = None) -> None:
        self._config = config or QueuePublisherConfig.from_env()
        self._queue_client: Optional[QueueClient] = None
        self._credential: Optional[DefaultAzureCredential] = None

    @property
    def queue_name(self) -> str:
        return self._config.queue_name

    def _get_queue_client(self) -> QueueClient:
        if self._queue_client is not None:
            return self._queue_client

        if self._config.account_key:
            credential = AzureNamedKeyCredential(self._config.account_name, self._config.account_key)
            self._queue_client = QueueClient(
                account_url=self._config.account_url,
                queue_name=self._config.queue_name,
                credential=credential,
                api_version=_storage_api_version(),
            )
            logger.info(
                "queue_publisher.client_initialized",
                extra={
                    "auth_mode": "shared_key",
                    "account_name": self._config.account_name,
                    "queue": self._config.queue_name,
                },
            )
            return self._queue_client

        self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self._queue_client = QueueClient(
            account_url=self._config.account_url,
            queue_name=self._config.queue_name,
            credential=self._credential,
            api_version=_storage_api_version(),
        )
        logger.info(
            "queue_publisher.client_initialized",
            extra={
                "auth_mode": "entra_id",
                "account_name": self._config.account_name,
                "queue": self._config.queue_name,
            },
        )
        return self._queue_client

    def publish_json(self, payload: Dict[str, Any]) -> None:
        try:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            client = self._get_queue_client()
            client.send_message(body)
            logger.info(
                "queue_publisher.message_published",
                extra={"queue": self._config.queue_name, "payload_type": payload.get("type")},
            )
        except AzureError as exc:
            logger.exception(
                "queue_publisher.publish_failed",
                extra={"queue": self._config.queue_name, "payload_type": payload.get("type")},
            )
            raise QueuePublisherError("Failed to publish queue message") from exc
