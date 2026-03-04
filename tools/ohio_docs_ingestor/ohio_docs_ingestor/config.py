from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _to_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _to_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    tenant_id: str
    source_system: str
    agency: str
    jurisdiction: str
    default_department_scope: str
    default_authority_level: int
    default_policy_type: str
    include_external_references: bool
    container_name: str
    max_docs: int
    rate_limit_seconds: float
    upload_concurrency: int
    user_agent: str
    max_mb: int
    das_index_url: str
    jfs_index_url: str
    poll_interval_seconds: int
    poll_timeout_seconds: int
    connect_timeout_seconds: int
    read_timeout_seconds: int
    retry_total: int
    database_url: str | None
    tool_root: Path
    out_root: Path
    manifests_dir: Path
    downloads_dir: Path
    reports_dir: Path
    state_dir: Path


def load_settings(*, tool_root: Path, agency_override: str | None = None, max_docs_override: int | None = None) -> Settings:
    load_dotenv(tool_root / ".env")

    out_root = tool_root / "out"
    manifests_dir = out_root / "manifests"
    downloads_dir = out_root / "downloads"
    reports_dir = out_root / "reports"
    state_dir = out_root / "state"

    for directory in (out_root, manifests_dir, downloads_dir, reports_dir, state_dir):
        directory.mkdir(parents=True, exist_ok=True)

    agency_value = (agency_override or os.getenv("AGENCY", "DAS")).strip().upper()
    max_docs_value = max_docs_override if max_docs_override is not None else _to_int("MAX_DOCS", 0)
    include_external_refs_value = (os.getenv("INCLUDE_EXTERNAL_REFERENCES", "false").strip().lower() in {"1", "true", "yes", "y", "on"})

    return Settings(
        api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/"),
        tenant_id=os.getenv("TENANT_ID", "00000000-0000-0000-0000-000000000001").strip(),
        source_system=os.getenv("SOURCE_SYSTEM", "ohio-docs").strip(),
        agency=agency_value,
        jurisdiction=os.getenv("JURISDICTION", "ohio").strip(),
        default_department_scope=os.getenv("DEFAULT_DEPARTMENT_SCOPE", "all").strip(),
        default_authority_level=_to_int("DEFAULT_AUTHORITY_LEVEL", 50),
        default_policy_type=os.getenv("DEFAULT_POLICY_TYPE", "external_policy").strip(),
        include_external_references=include_external_refs_value,
        container_name=os.getenv("CONTAINER_NAME", "policy-raw").strip(),
        max_docs=max(0, max_docs_value),
        rate_limit_seconds=max(0.0, _to_float("RATE_LIMIT_SECONDS", 1.0)),
        upload_concurrency=max(1, _to_int("UPLOAD_CONCURRENCY", 2)),
        user_agent=os.getenv("USER_AGENT", "MistrvPolicyBot/1.0 (+contact@example.com)").strip(),
        max_mb=max(1, _to_int("MAX_MB", 25)),
        das_index_url=os.getenv("DAS_INDEX_URL", "https://das.ohio.gov/employee-relations/policies").strip(),
        jfs_index_url=os.getenv("JFS_INDEX_URL", "").strip(),
        poll_interval_seconds=max(2, _to_int("POLL_INTERVAL_SECONDS", 10)),
        poll_timeout_seconds=max(30, _to_int("POLL_TIMEOUT_SECONDS", 1800)),
        connect_timeout_seconds=max(1, _to_int("CONNECT_TIMEOUT_SECONDS", 10)),
        read_timeout_seconds=max(5, _to_int("READ_TIMEOUT_SECONDS", 60)),
        retry_total=max(0, _to_int("RETRY_TOTAL", 3)),
        database_url=(os.getenv("DATABASE_URL") or "").strip() or None,
        tool_root=tool_root,
        out_root=out_root,
        manifests_dir=manifests_dir,
        downloads_dir=downloads_dir,
        reports_dir=reports_dir,
        state_dir=state_dir,
    )
