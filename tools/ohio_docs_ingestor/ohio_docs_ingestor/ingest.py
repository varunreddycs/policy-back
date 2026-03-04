from __future__ import annotations

import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .api_client import IngestionApiClient
from .config import Settings
from .download import download_documents
from .models import ManifestItem, RegisterResult
from .utils import read_json, write_json
from .verify import get_embedding_counts, wait_for_batch_completion


logger = logging.getLogger("ohio_docs_ingestor.ingest")


def _blob_path_for(item: ManifestItem, sha256_value: str, content_type: str) -> str:
    ext = ".pdf" if "pdf" in content_type.lower() or item.doc_type == "pdf" else ".html"
    return f"external/{item.agency.lower()}/{item.external_id}/{sha256_value[:12]}{ext}"


def _version_label(effective_date: str | None) -> str:
    if not effective_date:
        return "v1"
    try:
        dt = datetime.fromisoformat(effective_date)
        return dt.strftime("%Y%m%d")
    except Exception:
        return "v1"


def _register_payload(*, settings: Settings, item: ManifestItem, blob_path: str, sha256_value: str, content_type: str, content_length: int, run_id: str) -> dict:
    return {
        "container_name": settings.container_name,
        "blob_path": blob_path,
        "policy_external_id": f"ohio-{item.agency.lower()}-{item.external_id}",
        "policy_name": item.title,
        "version_label": _version_label(item.effective_date),
        "effective_date": item.effective_date,
        "title": item.title,
        "content_type": content_type,
        "content_length": content_length,
        "correlation_id": f"ohio-{item.agency.lower()}-{item.external_id}-{run_id}",
        "metadata": {
            "source_system": settings.source_system,
            "agency": item.agency,
            "policy_source_type": "external",
            "jurisdiction": settings.jurisdiction,
            "source_url": item.source_url,
            "content_sha256": sha256_value,
            "policy_type": item.suggested_policy_type or settings.default_policy_type,
            "department_scope": settings.default_department_scope,
            "authority_level": settings.default_authority_level,
        },
    }


def trigger_embeddings_backfill(settings: Settings, *, tenant_id: str) -> dict:
    before = get_embedding_counts(settings, tenant_id=tenant_id)
    cmd = [
        sys.executable,
        "-m",
        "apps.worker.jobs.embed_backfill",
        "--tenant-id",
        tenant_id,
        "--only-current",
    ]

    result = subprocess.run(
        cmd,
        cwd=str((settings.tool_root / ".." / "..").resolve()),
        capture_output=True,
        text=True,
        check=False,
    )
    after = get_embedding_counts(settings, tenant_id=tenant_id)

    return {
        "command": " ".join(cmd),
        "return_code": int(result.returncode),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "counts_before": before,
        "counts_after": after,
    }


def ingest_documents(settings: Settings, *, manifest_items: list[ManifestItem], run_id: str) -> dict:
    client = IngestionApiClient(settings)
    batch = client.create_batch(correlation_id=f"ohio-{settings.agency.lower()}-{run_id}")
    batch_id = str(batch["id"])

    logger.info("ingest.batch_created", extra={"extra_fields": {"batch_id": batch_id, "agency": settings.agency}})

    downloaded_items = download_documents(settings, manifest_items)
    results: list[RegisterResult] = []
    resume_state_path = settings.state_dir / f"{settings.agency.lower()}-ingest-state.json"
    resume_state = read_json(resume_state_path, {"documents": {}})
    if not isinstance(resume_state, dict):
        resume_state = {"documents": {}}
    resume_state.setdefault("documents", {})

    pending = []
    for downloaded in downloaded_items:
        item = downloaded.manifest_item
        if downloaded.skipped:
            results.append(
                RegisterResult(
                    external_id=item.external_id,
                    source_url=item.source_url,
                    blob_path="",
                    status="skipped",
                    detail=downloaded.skip_reason,
                )
            )
        else:
            state_key = f"{item.external_id}:{downloaded.sha256}"
            prior = resume_state["documents"].get(state_key, {})
            prior_status = str(prior.get("status", ""))
            if prior_status in {"registered", "conflict"}:
                results.append(
                    RegisterResult(
                        external_id=item.external_id,
                        source_url=item.source_url,
                        blob_path=str(prior.get("blob_path", "")),
                        status="resumed-skip",
                        detail=f"prior_status={prior_status}",
                        policy_version_id=prior.get("policy_version_id"),
                    )
                )
                continue
            pending.append(downloaded)

    def _process_download(downloaded):
        local_client = IngestionApiClient(settings)
        item = downloaded.manifest_item
        blob_path = _blob_path_for(item, downloaded.sha256, downloaded.content_type)
        upload = local_client.get_upload_url(
            batch_id=batch_id,
            container_name=settings.container_name,
            blob_path=blob_path,
            content_type=downloaded.content_type,
        )
        payload = downloaded.local_path.read_bytes()
        local_client.upload_blob(upload_sas_url=upload["upload_sas_url"], local_file=payload, content_type=downloaded.content_type)

        register_payload = _register_payload(
            settings=settings,
            item=item,
            blob_path=blob_path,
            sha256_value=downloaded.sha256,
            content_type=downloaded.content_type,
            content_length=downloaded.content_length,
            run_id=run_id,
        )
        status_code, register_response = local_client.register_document(batch_id=batch_id, payload=register_payload)

        if status_code in (200, 201):
            return RegisterResult(
                external_id=item.external_id,
                source_url=item.source_url,
                blob_path=blob_path,
                status="registered",
                policy_version_id=str(register_response.get("policy_version_id")) if register_response else None,
            )
        if status_code == 409:
            return RegisterResult(
                external_id=item.external_id,
                source_url=item.source_url,
                blob_path=blob_path,
                status="conflict",
                detail=json.dumps(register_response, ensure_ascii=False),
            )
        return RegisterResult(
            external_id=item.external_id,
            source_url=item.source_url,
            blob_path=blob_path,
            status="failed",
            detail=json.dumps(register_response, ensure_ascii=False),
        )

    with ThreadPoolExecutor(max_workers=max(1, settings.upload_concurrency)) as executor:
        futures = [executor.submit(_process_download, item) for item in pending]
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                matched_download = next(
                    (
                        d
                        for d in pending
                        if d.manifest_item.external_id == result.external_id and d.manifest_item.source_url == result.source_url
                    ),
                    None,
                )
                sha_key = matched_download.sha256 if matched_download else "unknown"
                resume_state["documents"][f"{result.external_id}:{sha_key}"] = {
                    "status": result.status,
                    "blob_path": result.blob_path,
                    "policy_version_id": result.policy_version_id,
                    "source_url": result.source_url,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "batch_id": batch_id,
                    "run_id": run_id,
                }
            except Exception as exc:
                logger.exception("ingest.document_failed", extra={"extra_fields": {"error": str(exc)}})

    write_json(resume_state_path, resume_state)

    successful_registers = len([r for r in results if r.status in {"registered", "conflict"}])
    if successful_registers == 0:
        wait_result = {
            "batch": client.get_batch(batch_id=batch_id),
            "counts": {"registered": 0, "processing": 0, "ready": 0, "failed": 0},
            "timed_out": False,
            "skipped_wait_reason": "no_registered_documents",
        }
    else:
        wait_result = wait_for_batch_completion(settings, api_client=client, batch_id=batch_id, tenant_id=settings.tenant_id)
    embedding_result = trigger_embeddings_backfill(settings, tenant_id=settings.tenant_id)

    report = {
        "run_id": run_id,
        "agency": settings.agency,
        "tenant_id": settings.tenant_id,
        "batch_id": batch_id,
        "batch_status": wait_result["batch"].get("status"),
        "timed_out": wait_result["timed_out"],
        "counts": wait_result["counts"],
        "documents": [result.__dict__ for result in results],
        "resume_state_path": str(resume_state_path),
        "embeddings": embedding_result,
    }
    report_path = settings.reports_dir / f"{run_id}-{settings.agency.lower()}-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(
        "ingest.completed",
        extra={
            "extra_fields": {
                "batch_id": batch_id,
                "registered": len([r for r in results if r.status == "registered"]),
                "conflict": len([r for r in results if r.status == "conflict"]),
                "skipped": len([r for r in results if r.status == "skipped"]),
                "failed": len([r for r in results if r.status == "failed"]),
                "report": str(report_path),
            }
        },
    )
    return report
