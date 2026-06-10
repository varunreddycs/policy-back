from __future__ import annotations

import logging
from typing import Any

import requests

from .config import Settings
from .utils import build_http_session


logger = logging.getLogger("ohio_docs_ingestor.api")


class IngestionApiClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = build_http_session(settings.user_agent)

    def _timeout(self) -> tuple[int, int]:
        return (self.settings.connect_timeout_seconds, self.settings.read_timeout_seconds)

    def create_batch(self, *, correlation_id: str) -> dict[str, Any]:
        payload = {
            "tenant_id": self.settings.tenant_id,
            "source_system": self.settings.source_system,
            "correlation_id": correlation_id,
        }
        url = f"{self.settings.api_base_url}/v1/ingest/batches"
        response = self.session.post(url, json=payload, timeout=self._timeout())
        response.raise_for_status()
        return response.json()

    def get_batch(self, *, batch_id: str) -> dict[str, Any]:
        url = f"{self.settings.api_base_url}/v1/ingest/batches/{batch_id}"
        response = self.session.get(url, params={"tenant_id": self.settings.tenant_id}, timeout=self._timeout())
        response.raise_for_status()
        return response.json()

    def get_upload_url(self, *, batch_id: str, container_name: str, blob_path: str, content_type: str) -> dict[str, Any]:
        url = f"{self.settings.api_base_url}/v1/ingest/batches/{batch_id}/upload-urls"
        payload = {
            "container_name": container_name,
            "blob_path": blob_path,
            "content_type": content_type,
        }
        response = self.session.post(url, params={"tenant_id": self.settings.tenant_id}, json=payload, timeout=self._timeout())
        response.raise_for_status()
        return response.json()

    def upload_blob(self, *, upload_sas_url: str, local_file: bytes, content_type: str) -> None:
        headers = {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type,
        }
        response = requests.put(upload_sas_url, data=local_file, headers=headers, timeout=(self.settings.connect_timeout_seconds, 180))
        response.raise_for_status()

    def register_document(self, *, batch_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        url = f"{self.settings.api_base_url}/v1/ingest/batches/{batch_id}/register"
        response = self.session.post(url, params={"tenant_id": self.settings.tenant_id}, json=payload, timeout=self._timeout())
        data = {}
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        return response.status_code, data
