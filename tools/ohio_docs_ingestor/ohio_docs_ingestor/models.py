from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ManifestItem:
    source_url: str
    title: str
    doc_type: str
    external_id: str
    suggested_policy_type: str | None
    effective_date: str | None
    agency: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadedItem:
    manifest_item: ManifestItem
    local_path: Path
    sha256: str
    content_type: str
    content_length: int
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class RegisterResult:
    external_id: str
    source_url: str
    blob_path: str
    status: str
    detail: str | None = None
    policy_version_id: str | None = None
