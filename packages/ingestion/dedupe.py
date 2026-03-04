from __future__ import annotations

from typing import Any, Dict

from packages.db.models.policy_models import metadata_sha256, sha256_hex


def content_hash(data: bytes) -> str:
    return sha256_hex(data)


def metadata_hash(metadata: Dict[str, Any]) -> str:
    return metadata_sha256(metadata)
