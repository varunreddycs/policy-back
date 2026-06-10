from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def now_utc() -> datetime:
    return datetime.now(UTC)


def run_stamp() -> str:
    return now_utc().strftime("%Y%m%dT%H%M%SZ")


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def title_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def parse_effective_date(path: Path) -> str | None:
    match = DATE_RE.search(path.name)
    if not match:
        return None
    try:
        datetime.strptime(match.group(1), "%Y-%m-%d")
        return match.group(1)
    except ValueError:
        return None


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".txt":
        return "text/plain"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def with_rate_limit(last_called: float, wait_seconds: float) -> float:
    if wait_seconds <= 0:
        return time.monotonic()
    now = time.monotonic()
    delta = now - last_called
    if delta < wait_seconds:
        time.sleep(wait_seconds - delta)
    return time.monotonic()


def build_session(user_agent: str) -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PUT"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": user_agent})
    return session


def collect_local_files(input_dir: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".txt", ".pdf"}:
            continue
        files.append(path)
    if max_files > 0:
        return files[:max_files]
    return files


def load_sidecar_source_url(file_path: Path) -> str | None:
    sidecar = file_path.with_suffix(".json")
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        value = payload.get("source_url")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_slug(value: str) -> str:
    text = unquote((value or "").strip())
    # Crawler-safe filenames may encode specific URL bytes as _XX.
    text = re.sub(r"_28", "(", text, flags=re.IGNORECASE)
    text = re.sub(r"_29", ")", text, flags=re.IGNORECASE)
    text = re.sub(r"_2b", "+", text, flags=re.IGNORECASE)
    text = re.sub(r"_20", " ", text, flags=re.IGNORECASE)
    text = text.lower().replace("+", "-")
    text = text.replace("_", "-")
    text = re.sub(r"[^a-z0-9-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def load_policy_links_lookup(input_dir: Path) -> dict[str, str]:
    # Expected path from crawler output: <input_dir_parent>/policy_links.json
    links_path = input_dir.parent / "policy_links.json"
    if not links_path.exists():
        return {}

    try:
        payload = json.loads(links_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, list):
        return {}

    lookup: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, str) or not item.strip():
            continue
        url = item.strip()
        slug = url.rsplit("/", 1)[-1]
        normalized = _normalize_slug(slug)
        if normalized and normalized not in lookup:
            lookup[normalized] = url
    return lookup


def infer_source_url_from_lookup(file_path: Path, links_lookup: dict[str, str]) -> str | None:
    if not links_lookup:
        return None

    stem = file_path.stem
    base = stem.split("__", 1)[0]
    normalized_base = _normalize_slug(base)
    if normalized_base in links_lookup:
        return links_lookup[normalized_base]

    # Secondary fallback for occasional naming drift between filenames and URL slugs.
    for key, url in links_lookup.items():
        if key == normalized_base or key in normalized_base or normalized_base in key:
            return url
    return None


@dataclass
class FilePlan:
    file_path: Path
    relative_no_ext: str
    policy_external_id: str
    policy_name: str
    title: str
    effective_date: str | None
    content_type: str
    file_sha256: str
    blob_path: str
    version_label: str
    metadata: dict[str, Any]


class LocalIngestClient:
    def __init__(self, api_base_url: str, tenant_id: str, session: requests.Session, timeout: tuple[int, int]) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.session = session
        self.timeout = timeout

    def create_batch(self, source_system: str, correlation_id: str) -> dict[str, Any]:
        url = f"{self.api_base_url}/v1/ingest/batches"
        payload = {
            "tenant_id": self.tenant_id,
            "source_system": source_system,
            "correlation_id": correlation_id,
        }
        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_upload_url(self, batch_id: str, container_name: str, blob_path: str, content_type: str) -> dict[str, Any]:
        url = f"{self.api_base_url}/v1/ingest/batches/{batch_id}/upload-urls"
        payload = {
            "container_name": container_name,
            "blob_path": blob_path,
            "content_type": content_type,
            "expires_in_minutes": 60,
        }
        response = self.session.post(url, params={"tenant_id": self.tenant_id}, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def upload_blob(self, upload_sas_url: str, file_path: Path, content_type: str) -> None:
        headers = {"x-ms-blob-type": "BlockBlob", "Content-Type": content_type}
        with file_path.open("rb") as handle:
            response = requests.put(
                upload_sas_url,
                data=handle,
                headers=headers,
                timeout=(self.timeout[0], 300),
            )
        response.raise_for_status()

    def register_document(self, batch_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        url = f"{self.api_base_url}/v1/ingest/batches/{batch_id}/register"
        response = self.session.post(url, params={"tenant_id": self.tenant_id}, json=payload, timeout=self.timeout)
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}
        return response.status_code, body

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        url = f"{self.api_base_url}/v1/ingest/batches/{batch_id}"
        response = self.session.get(url, params={"tenant_id": self.tenant_id}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


def extract_batch_counts(batch: dict[str, Any]) -> dict[str, int]:
    # Try common shapes returned by APIs.
    candidates: list[dict[str, Any]] = []
    for key in ("counts", "status_counts", "summary"):
        value = batch.get(key)
        if isinstance(value, dict):
            candidates.append(value)

    counts = {"registered": 0, "processing": 0, "ready": 0, "failed": 0}
    for c in candidates:
        for key in counts:
            if key in c and isinstance(c[key], int):
                counts[key] = c[key]
    return counts


def poll_batch_until_done(
    client: LocalIngestClient,
    batch_id: str,
    expected_register_attempts: int,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> dict[str, Any]:
    start = time.monotonic()
    last_batch: dict[str, Any] | None = None

    while True:
        batch = client.get_batch(batch_id)
        last_batch = batch
        counts = extract_batch_counts(batch)
        status = str(batch.get("status", "unknown"))

        print(
            f"poll status={status} registered={counts['registered']} processing={counts['processing']} "
            f"ready={counts['ready']} failed={counts['failed']}"
        )

        done_by_status = status.lower() in {"completed", "complete", "failed", "cancelled"}
        done_by_counts = expected_register_attempts > 0 and (counts["ready"] + counts["failed"]) >= expected_register_attempts
        if done_by_status or done_by_counts:
            return {
                "batch": batch,
                "counts": counts,
                "timed_out": False,
            }

        if (time.monotonic() - start) >= timeout_seconds:
            return {
                "batch": batch,
                "counts": counts,
                "timed_out": True,
            }

        time.sleep(poll_interval_seconds)


def plan_files(
    files: list[Path],
    input_dir: Path,
    source_system: str,
    agency: str,
    jurisdiction: str,
    department_scope: str,
    authority_level: int,
    policy_type: str,
    blob_prefix: str,
    run_stamp_value: str,
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    links_lookup = load_policy_links_lookup(input_dir)

    normalized_blob_prefix = blob_prefix.strip()
    if not normalized_blob_prefix:
        normalized_blob_prefix = f"external/{agency.lower()}/"
    if not normalized_blob_prefix.endswith("/"):
        normalized_blob_prefix += "/"

    for path in files:
        rel_path = path.relative_to(input_dir)
        rel_no_ext = str(rel_path.with_suffix("")).replace("\\", "/")

        external_id = sha1_text(rel_no_ext)[:12]
        policy_external_id = f"{source_system}-{agency.lower()}-{external_id}"
        policy_name = title_from_filename(path)
        content_type = guess_content_type(path)
        file_sha = sha256_file(path)

        version_label = f"v1-{run_stamp_value}-{file_sha[:8]}"
        blob_path = f"{normalized_blob_prefix}{policy_external_id}/{run_stamp_value}-{path.name}"

        metadata: dict[str, Any] = {
            "source_system": source_system,
            "agency": agency,
            "jurisdiction": jurisdiction,
            "policy_source_type": "external",
            "source_file": str(rel_path).replace("\\", "/"),
            "authority_level": authority_level,
            "department_scope": department_scope,
            "policy_type": policy_type,
            "file_sha256": file_sha,
            "content_type": content_type,
        }
        source_url = load_sidecar_source_url(path)
        if not source_url:
            source_url = infer_source_url_from_lookup(path, links_lookup)
        if source_url:
            metadata["source_url"] = source_url

        plans.append(
            FilePlan(
                file_path=path,
                relative_no_ext=rel_no_ext,
                policy_external_id=policy_external_id,
                policy_name=policy_name,
                title=policy_name,
                effective_date=parse_effective_date(path),
                content_type=content_type,
                file_sha256=file_sha,
                blob_path=blob_path,
                version_label=version_label,
                metadata=metadata,
            )
        )

    return plans


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local files -> ingestion wiring for Policy-to-Production")
    parser.add_argument("--input-dir", required=True, help="Folder containing .txt and .pdf files")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--source-system", default="ohio-docs")
    parser.add_argument("--agency", default="DAS")
    parser.add_argument("--jurisdiction", default="ohio")
    parser.add_argument("--department-scope", default="all")
    parser.add_argument("--authority-level", type=int, default=50)
    parser.add_argument("--policy-type", default="external_policy")
    parser.add_argument("--only-current", default="true")
    parser.add_argument("--max-files", type=int, default=0, help="0 = all")
    parser.add_argument("--rate-limit-seconds", type=float, default=0.2)
    parser.add_argument("--container-name", default="policies")
    parser.add_argument("--blob-prefix", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poll-timeout-seconds", type=int, default=20 * 60)
    parser.add_argument("--poll-interval-seconds", type=int, default=10)
    parser.add_argument("--connect-timeout-seconds", type=int, default=10)
    parser.add_argument("--read-timeout-seconds", type=int, default=60)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"ERROR: input directory not found: {input_dir}")
        return 2

    stamp = run_stamp()
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report-{stamp}.json"

    files = collect_local_files(input_dir, args.max_files)
    if not files:
        print("No .txt/.pdf files found.")
        report_path.write_text(json.dumps({"run_stamp": stamp, "files": []}, indent=2), encoding="utf-8")
        return 0

    plans = plan_files(
        files=files,
        input_dir=input_dir,
        source_system=args.source_system,
        agency=args.agency,
        jurisdiction=args.jurisdiction,
        department_scope=args.department_scope,
        authority_level=args.authority_level,
        policy_type=args.policy_type,
        blob_prefix=args.blob_prefix or f"external/{args.agency.lower()}/",
        run_stamp_value=stamp,
    )

    report: dict[str, Any] = {
        "run_stamp": stamp,
        "dry_run": bool(args.dry_run),
        "input_dir": str(input_dir),
        "tenant_id": args.tenant_id,
        "api_base_url": args.api_base_url,
        "source_system": args.source_system,
        "agency": args.agency,
        "batch_id": None,
        "only_current": str(args.only_current).lower() in {"1", "true", "yes", "y", "on"},
        "files_total": len(plans),
        "results": [],
    }

    print(f"Run stamp: {stamp}")
    print(f"Discovered files: {len(plans)}")

    if args.dry_run:
        for plan in plans:
            report["results"].append(
                {
                    "file": str(plan.file_path),
                    "policy_external_id": plan.policy_external_id,
                    "blob_path": plan.blob_path,
                    "version_label": plan.version_label,
                    "effective_date": plan.effective_date,
                    "content_type": plan.content_type,
                    "file_sha256": plan.file_sha256,
                    "status": "dry-run",
                }
            )
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Dry-run only. Report: {report_path}")
        return 0

    session = build_session("LocalFileIngestor/1.0")
    timeout = (max(1, args.connect_timeout_seconds), max(1, args.read_timeout_seconds))
    client = LocalIngestClient(args.api_base_url, args.tenant_id, session, timeout)

    batch = client.create_batch(source_system=args.source_system, correlation_id=stamp)
    batch_id = str(batch.get("id") or batch.get("batch_id") or "")
    if not batch_id:
        print("ERROR: create_batch did not return batch id")
        return 1

    report["batch_id"] = batch_id
    print(f"Batch created: {batch_id}")

    last_called = 0.0
    register_attempts = 0
    created_count = 0
    conflict_count = 0
    failed_count = 0

    for idx, plan in enumerate(plans, start=1):
        result: dict[str, Any] = {
            "file": str(plan.file_path),
            "relative_no_ext": plan.relative_no_ext,
            "policy_external_id": plan.policy_external_id,
            "blob_path": plan.blob_path,
            "version_label": plan.version_label,
            "effective_date": plan.effective_date,
            "file_sha256": plan.file_sha256,
            "content_type": plan.content_type,
        }

        try:
            print(f"[{idx}/{len(plans)}] {plan.file_path.name}")
            print(f"  sha256={plan.file_sha256}")

            last_called = with_rate_limit(last_called, args.rate_limit_seconds)
            upload_info = client.get_upload_url(
                batch_id=batch_id,
                container_name=args.container_name,
                blob_path=plan.blob_path,
                content_type=plan.content_type,
            )
            upload_sas_url = str(upload_info.get("upload_sas_url") or "")
            if not upload_sas_url:
                raise RuntimeError("upload_sas_url missing from upload-urls response")

            client.upload_blob(upload_sas_url=upload_sas_url, file_path=plan.file_path, content_type=plan.content_type)

            register_payload = {
                "container_name": args.container_name,
                "blob_path": plan.blob_path,
                "policy_external_id": plan.policy_external_id,
                "policy_name": plan.policy_name,
                "version_label": plan.version_label,
                "effective_date": plan.effective_date,
                "title": plan.title,
                "metadata": plan.metadata,
                "correlation_id": f"{args.source_system}-{args.agency.lower()}-{plan.policy_external_id.split('-')[-1]}-{stamp}",
            }

            last_called = with_rate_limit(last_called, args.rate_limit_seconds)
            register_attempts += 1
            status_code, register_body = client.register_document(batch_id=batch_id, payload=register_payload)

            policy_id = register_body.get("policy_id") if isinstance(register_body, dict) else None
            policy_version_id = register_body.get("policy_version_id") if isinstance(register_body, dict) else None
            print(f"  register status={status_code} policy_id={policy_id} policy_version_id={policy_version_id}")

            result["register_status_code"] = status_code
            result["register_response"] = register_body
            result["policy_id"] = policy_id
            result["policy_version_id"] = policy_version_id

            if status_code in (200, 201):
                created_count += 1
                result["status"] = "registered"
            elif status_code == 409:
                conflict_count += 1
                result["status"] = "conflict"
            else:
                failed_count += 1
                result["status"] = "failed"
        except Exception as exc:
            failed_count += 1
            result["status"] = "failed"
            result["error"] = str(exc)
            print(f"  ERROR: {exc}")

        report["results"].append(result)

    poll_result = poll_batch_until_done(
        client=client,
        batch_id=batch_id,
        expected_register_attempts=register_attempts,
        timeout_seconds=max(30, args.poll_timeout_seconds),
        poll_interval_seconds=max(2, args.poll_interval_seconds),
    )

    report["batch_poll"] = poll_result
    report["summary"] = {
        "policies_created_count": created_count,
        "register_conflict_count": conflict_count,
        "register_failed_count": failed_count,
        "register_attempted_count": register_attempts,
        "batch_ready_count": poll_result["counts"].get("ready", 0),
        "batch_failed_count": poll_result["counts"].get("failed", 0),
        "timed_out": bool(poll_result.get("timed_out")),
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n==== INGEST SUMMARY ====")
    print(f"batch_id: {batch_id}")
    print(f"policies_created_count: {created_count}")
    print(f"versions_ready: {poll_result['counts'].get('ready', 0)}")
    print(f"versions_failed: {poll_result['counts'].get('failed', 0)}")
    print(f"report: {report_path}")

    only_current_flag = "--only-current" if report["only_current"] else ""
    print("suggested next command:")
    print(f"  python -m apps.worker.jobs.embed_backfill --tenant-id {args.tenant_id} {only_current_flag}".strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
