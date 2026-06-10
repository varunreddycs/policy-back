from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.core.credentials import AzureNamedKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobClient,
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)


logger = logging.getLogger(__name__)


class BlobServiceError(RuntimeError):
    """Base error for blob operations."""


class BlobNotFoundError(BlobServiceError):
    """Raised when a requested blob does not exist."""


class BlobConfigurationError(BlobServiceError):
    """Raised when blob service configuration is invalid/incomplete."""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise BlobConfigurationError(f"Missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value if value else None


def _storage_api_version() -> Optional[str]:
    value = os.getenv("AZURE_STORAGE_API_VERSION")
    return value if value else None


def _normalize_blob_path(blob_path: str) -> str:
    blob_path = (blob_path or "").strip()
    if not blob_path:
        raise ValueError("blob_path must be non-empty")
    return blob_path.lstrip("/")


@dataclass(frozen=True, slots=True)
class BlobServiceConfig:
    account_url: str
    client_account_url: str
    account_name: str
    account_key: Optional[str]
    default_sas_expiry_minutes: int = 15

    @staticmethod
    def from_env() -> "BlobServiceConfig":
        account_url = _optional_env("AZURE_STORAGE_ACCOUNT_URL")
        client_account_url = (
            _optional_env("AZURE_STORAGE_BLOB_ACCOUNT_URL_INTERNAL")
            or _optional_env("AZURE_STORAGE_ACCOUNT_URL_INTERNAL")
        )
        account_name = _optional_env("AZURE_STORAGE_ACCOUNT_NAME")
        account_key = _optional_env("AZURE_STORAGE_ACCOUNT_KEY")

        if not account_url:
            if not account_name:
                raise BlobConfigurationError(
                    "Set AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_ACCOUNT_NAME."
                )
            account_url = f"https://{account_name}.blob.core.windows.net"
        if not client_account_url:
            client_account_url = account_url
        if not account_name:
            try:
                host = account_url.split("//", 1)[1].split("/", 1)[0]
                account_name = host.split(".", 1)[0]
            except Exception as exc:  # pragma: no cover
                raise BlobConfigurationError(
                    "Unable to infer account name from AZURE_STORAGE_ACCOUNT_URL; "
                    "set AZURE_STORAGE_ACCOUNT_NAME."
                ) from exc

        expiry_str = _optional_env("AZURE_STORAGE_SAS_EXPIRY_MINUTES")
        expiry = 15
        if expiry_str:
            try:
                expiry = int(expiry_str)
            except ValueError as exc:
                raise BlobConfigurationError(
                    "AZURE_STORAGE_SAS_EXPIRY_MINUTES must be an integer"
                ) from exc
        if expiry < 1 or expiry > 24 * 60:
            raise BlobConfigurationError("AZURE_STORAGE_SAS_EXPIRY_MINUTES must be in [1, 1440]")

        return BlobServiceConfig(
            account_url=account_url,
            client_account_url=client_account_url,
            account_name=account_name,
            account_key=account_key,
            default_sas_expiry_minutes=expiry,
        )


class BlobService:
    """Azure Blob Storage integration."""

    def __init__(self, config: Optional[BlobServiceConfig] = None) -> None:
        self._config = config or BlobServiceConfig.from_env()
        self._service_client: Optional[BlobServiceClient] = None
        self._credential: Optional[DefaultAzureCredential] = None

    @property
    def account_url(self) -> str:
        return self._config.account_url

    def _get_service_client(self) -> BlobServiceClient:
        if self._service_client is not None:
            return self._service_client

        if self._config.account_key:
            credential = AzureNamedKeyCredential(self._config.account_name, self._config.account_key)
            self._service_client = BlobServiceClient(
                account_url=self._config.client_account_url,
                credential=credential,
                api_version=_storage_api_version(),
            )
            logger.info(
                "blob_service.client_initialized",
                extra={
                    "auth_mode": "shared_key",
                    "account_name": self._config.account_name,
                },
            )
            return self._service_client

        self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self._service_client = BlobServiceClient(
            account_url=self._config.client_account_url,
            credential=self._credential,
            api_version=_storage_api_version(),
        )
        logger.info(
            "blob_service.client_initialized",
            extra={
                "auth_mode": "entra_id",
                "account_name": self._config.account_name,
            },
        )
        return self._service_client

    def _get_blob_client(self, container_name: str, blob_path: str) -> BlobClient:
        if not container_name or not container_name.strip():
            raise ValueError("container_name must be non-empty")
        blob_path = _normalize_blob_path(blob_path)
        return self._get_service_client().get_blob_client(container=container_name, blob=blob_path)

    def get_blob_uri(self, container_name: str, blob_path: str) -> str:
        if not container_name or not container_name.strip():
            raise ValueError("container_name must be non-empty")
        blob_path = _normalize_blob_path(blob_path)
        base = (self._config.account_url or "").rstrip("/")
        return f"{base}/{container_name.strip()}/{blob_path}"

    def generate_upload_sas_url(
        self,
        container_name: str,
        blob_path: str,
        *,
        expires_in_minutes: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> str:
        expiry_minutes = expires_in_minutes or self._config.default_sas_expiry_minutes
        if expiry_minutes < 1 or expiry_minutes > 24 * 60:
            raise ValueError("expires_in_minutes must be in [1, 1440]")

        blob_path = _normalize_blob_path(blob_path)
        now = datetime.now(UTC)
        starts_on = now - timedelta(minutes=5)
        expires_on = now + timedelta(minutes=expiry_minutes)
        permissions = BlobSasPermissions(create=True, write=True)

        try:
            if self._config.account_key:
                sas_token = generate_blob_sas(
                    account_name=self._config.account_name,
                    container_name=container_name,
                    blob_name=blob_path,
                    account_key=self._config.account_key,
                    permission=permissions,
                    expiry=expires_on,
                    start=starts_on,
                    content_type=content_type,
                )
                url = f"{self.get_blob_uri(container_name, blob_path)}?{sas_token}"
                logger.info(
                    "blob_service.upload_sas_generated",
                    extra={
                        "auth_mode": "shared_key",
                        "container": container_name,
                        "blob": blob_path,
                        "expires_in_minutes": expiry_minutes,
                    },
                )
                return url

            service_client = self._get_service_client()
            udk = service_client.get_user_delegation_key(
                key_start_time=starts_on, key_expiry_time=expires_on
            )
            sas_token = generate_blob_sas(
                account_name=self._config.account_name,
                container_name=container_name,
                blob_name=blob_path,
                user_delegation_key=udk,
                permission=permissions,
                expiry=expires_on,
                start=starts_on,
                content_type=content_type,
            )
            url = f"{self.get_blob_uri(container_name, blob_path)}?{sas_token}"
            logger.info(
                "blob_service.upload_sas_generated",
                extra={
                    "auth_mode": "entra_id",
                    "container": container_name,
                    "blob": blob_path,
                    "expires_in_minutes": expiry_minutes,
                },
            )
            return url
        except AzureError as exc:
            logger.exception(
                "blob_service.upload_sas_failed",
                extra={
                    "container": container_name,
                    "blob": blob_path,
                    "expires_in_minutes": expiry_minutes,
                },
            )
            raise BlobServiceError("Failed to generate upload SAS URL") from exc

    def download_blob_bytes(
        self,
        container_name: str,
        blob_path: str,
        *,
        max_concurrency: int = 4,
    ) -> bytes:
        blob_client = self._get_blob_client(container_name, blob_path)
        try:
            downloader = blob_client.download_blob(max_concurrency=max_concurrency)
            data = downloader.readall()
            logger.info(
                "blob_service.download_succeeded",
                extra={
                    "container": container_name,
                    "blob": _normalize_blob_path(blob_path),
                    "bytes": len(data) if data is not None else 0,
                },
            )
            return data
        except ResourceNotFoundError as exc:
            logger.warning(
                "blob_service.not_found",
                extra={
                    "container": container_name,
                    "blob": _normalize_blob_path(blob_path),
                },
            )
            raise BlobNotFoundError("Blob not found") from exc
        except AzureError as exc:
            logger.exception(
                "blob_service.download_failed",
                extra={
                    "container": container_name,
                    "blob": _normalize_blob_path(blob_path),
                },
            )
            raise BlobServiceError("Failed to download blob") from exc

    def upload_blob_bytes(
        self,
        container_name: str,
        blob_path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> str:
        blob_client = self._get_blob_client(container_name, blob_path)
        try:
            blob_client.upload_blob(
                data,
                overwrite=overwrite,
                content_settings=ContentSettings(content_type=content_type),
            )
            logger.info(
                "blob_service.upload_succeeded",
                extra={
                    "container": container_name,
                    "blob": _normalize_blob_path(blob_path),
                    "bytes": len(data),
                    "content_type": content_type,
                    "overwrite": overwrite,
                },
            )
            return self.get_blob_uri(container_name, blob_path)
        except AzureError as exc:
            logger.exception(
                "blob_service.upload_failed",
                extra={
                    "container": container_name,
                    "blob": _normalize_blob_path(blob_path),
                    "bytes": len(data) if data is not None else 0,
                    "content_type": content_type,
                    "overwrite": overwrite,
                },
            )
            raise BlobServiceError("Failed to upload blob") from exc


__all__ = [
    "BlobService",
    "BlobServiceConfig",
    "BlobServiceError",
    "BlobNotFoundError",
    "BlobConfigurationError",
]
