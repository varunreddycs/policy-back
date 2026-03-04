from __future__ import annotations

import uuid


def extracted_blob_path(*, tenant_id: uuid.UUID, policy_id: uuid.UUID, policy_version_id: uuid.UUID) -> str:
    return f"tenants/{tenant_id}/policies/{policy_id}/versions/{policy_version_id}/extracted.json"
