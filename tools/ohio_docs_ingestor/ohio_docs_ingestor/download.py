from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from requests import RequestException

from .config import Settings
from .models import DownloadedItem, ManifestItem
from .utils import build_http_session, read_json, with_rate_limit, write_json


logger = logging.getLogger("ohio_docs_ingestor.download")


def _extension_for(item: ManifestItem, content_type: str) -> str:
    if item.doc_type == "pdf":
        return ".pdf"
    if "pdf" in (content_type or "").lower() or urlparse(item.source_url).path.lower().endswith(".pdf"):
        return ".pdf"
    return ".html"


def _load_index(path: Path) -> dict:
    default = {"documents": {}}
    loaded = read_json(path, default)
    if not isinstance(loaded, dict):
        return default
    loaded.setdefault("documents", {})
    return loaded


def _looks_like_html_error(prefix_bytes: bytes) -> bool:
    text = prefix_bytes[:1024].decode("utf-8", errors="ignore").strip().lower()
    return text.startswith("<!doctype html") or text.startswith("<html") or "<body" in text


def download_documents(settings: Settings, items: list[ManifestItem]) -> list[DownloadedItem]:
    agency = settings.agency.upper()
    max_bytes = settings.max_mb * 1024 * 1024
    downloads_dir = settings.downloads_dir / agency.lower()
    downloads_dir.mkdir(parents=True, exist_ok=True)

    index_path = settings.state_dir / "download_index.json"
    index_db = _load_index(index_path)
    session = build_http_session(settings.user_agent)

    downloaded: list[DownloadedItem] = []
    last_called = 0.0

    for item in items:
        doc_entry = index_db["documents"].get(item.source_url, {})
        existing_sha = doc_entry.get("current_sha256")
        existing_path = doc_entry.get("current_path")

        if existing_sha and existing_path and os.path.exists(existing_path):
            downloaded.append(
                DownloadedItem(
                    manifest_item=item,
                    local_path=Path(existing_path),
                    sha256=existing_sha,
                    content_type=doc_entry.get("content_type", "application/octet-stream"),
                    content_length=int(doc_entry.get("content_length", 0) or 0),
                    skipped=False,
                    skip_reason="cached_unchanged",
                )
            )
            continue

        last_called = with_rate_limit(last_called, settings.rate_limit_seconds)
        try:
            head = session.head(
                item.source_url,
                allow_redirects=True,
                timeout=(settings.connect_timeout_seconds, settings.read_timeout_seconds),
            )
            if head.status_code >= 400:
                logger.warning(
                    "download.head_unavailable",
                    extra={"extra_fields": {"url": item.source_url, "status": int(head.status_code)}},
                )
                head = None
        except RequestException as exc:
            logger.warning("download.head_failed", extra={"extra_fields": {"url": item.source_url, "error": str(exc)}})
            head = None

        content_length_header = (head.headers.get("Content-Length") if head is not None else None)
        content_type = ((head.headers.get("Content-Type") if head is not None else None) or "application/octet-stream").split(";")[0].strip()

        if content_length_header:
            content_length = int(content_length_header)
            if content_length > max_bytes:
                downloaded.append(
                    DownloadedItem(
                        manifest_item=item,
                        local_path=downloads_dir / f"{item.external_id}.skip",
                        sha256="",
                        content_type=content_type,
                        content_length=content_length,
                        skipped=True,
                        skip_reason=f"too_large>{settings.max_mb}MB",
                    )
                )
                logger.warning(
                    "download.skipped_too_large",
                    extra={"extra_fields": {"url": item.source_url, "bytes": content_length}},
                )
                continue

        attempt_error = None
        response = None
        for attempt in range(max(1, settings.retry_total + 1)):
            try:
                response = session.get(
                    item.source_url,
                    stream=True,
                    timeout=(settings.connect_timeout_seconds, settings.read_timeout_seconds),
                )
                response.raise_for_status()
                break
            except RequestException as exc:
                attempt_error = exc
                backoff = min(8.0, 0.8 * (2 ** attempt))
                time.sleep(backoff)

        if response is None:
            downloaded.append(
                DownloadedItem(
                    manifest_item=item,
                    local_path=downloads_dir / f"{item.external_id}.failed",
                    sha256="",
                    content_type=content_type,
                    content_length=0,
                    skipped=True,
                    skip_reason=f"network_error:{attempt_error}",
                )
            )
            logger.error("download.failed", extra={"extra_fields": {"url": item.source_url, "error": str(attempt_error)}})
            continue

        content_type = (response.headers.get("Content-Type") or content_type or "application/octet-stream").split(";")[0].strip()

        ext = _extension_for(item, content_type)
        output_path = downloads_dir / f"{item.external_id}{ext}"

        sha256 = hashlib.sha256()
        total = 0
        first_chunk = b""
        with output_path.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                if not first_chunk:
                    first_chunk = chunk[:1024]
                total += len(chunk)
                if total > max_bytes:
                    file_handle.close()
                    output_path.unlink(missing_ok=True)
                    downloaded.append(
                        DownloadedItem(
                            manifest_item=item,
                            local_path=output_path,
                            sha256="",
                            content_type=content_type,
                            content_length=total,
                            skipped=True,
                            skip_reason=f"too_large_stream>{settings.max_mb}MB",
                        )
                    )
                    logger.warning(
                        "download.skipped_too_large_stream",
                        extra={"extra_fields": {"url": item.source_url, "bytes": total}},
                    )
                    break
                file_handle.write(chunk)
                sha256.update(chunk)
            else:
                if item.doc_type == "pdf" and ("html" in content_type.lower() or _looks_like_html_error(first_chunk)):
                    output_path.unlink(missing_ok=True)
                    downloaded.append(
                        DownloadedItem(
                            manifest_item=item,
                            local_path=output_path,
                            sha256="",
                            content_type=content_type,
                            content_length=total,
                            skipped=True,
                            skip_reason="unexpected_html_for_pdf",
                        )
                    )
                    logger.warning(
                        "download.unexpected_content",
                        extra={"extra_fields": {"url": item.source_url, "content_type": content_type}},
                    )
                    continue
                digest = sha256.hexdigest()
                index_db["documents"][item.source_url] = {
                    "current_sha256": digest,
                    "current_path": str(output_path),
                    "content_type": content_type,
                    "content_length": total,
                    "sha_to_path": {
                        **(doc_entry.get("sha_to_path") or {}),
                        digest: str(output_path),
                    },
                }
                downloaded.append(
                    DownloadedItem(
                        manifest_item=item,
                        local_path=output_path,
                        sha256=digest,
                        content_type=content_type,
                        content_length=total,
                    )
                )

    write_json(index_path, index_db)
    logger.info(
        "download.completed",
        extra={
            "extra_fields": {
                "agency": agency,
                "total": len(downloaded),
                "downloaded": len([x for x in downloaded if not x.skipped]),
                "skipped": len([x for x in downloaded if x.skipped]),
                "index_db": str(index_path),
            }
        },
    )
    return downloaded
