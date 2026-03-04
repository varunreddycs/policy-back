from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from apps.api.deps import get_blob_service, get_policy_query_service
from apps.api.schemas.policies import PolicyResponse, PolicyVersionResponse
from packages.db.policy_query_service import PolicyQueryService
from packages.storage.blob_service import BlobService


router = APIRouter(prefix="/v1", tags=["Policies"])


@router.get(
    "/policies",
    response_model=List[PolicyResponse],
    summary="List policies",
    description="Lists policies for a tenant.",
)
def list_policies(
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    service: PolicyQueryService = Depends(get_policy_query_service),
) -> List[PolicyResponse]:
    return service.list_policies(tenant_id=tenant_id)


@router.get(
    "/policies/{policy_id}/versions",
    response_model=List[PolicyVersionResponse],
    summary="List policy versions",
    description="Lists immutable policy versions for a policy (tenant-scoped).",
)
def list_policy_versions(
    policy_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    service: PolicyQueryService = Depends(get_policy_query_service),
    blob_service: BlobService = Depends(get_blob_service),
) -> List[PolicyVersionResponse]:
    versions = service.list_policy_versions(tenant_id=tenant_id, policy_id=policy_id)

    results: List[PolicyVersionResponse] = []
    for version in versions:
        raw_blob_uri = blob_service.get_blob_uri(version.blob_container, version.blob_name)
        if hasattr(PolicyVersionResponse, "model_validate"):
            resp = PolicyVersionResponse.model_validate(version)  # type: ignore[attr-defined]
            resp = resp.model_copy(update={"raw_blob_uri": raw_blob_uri})  # type: ignore[attr-defined]
        else:  # pragma: no cover
            resp = PolicyVersionResponse.from_orm(version)  # type: ignore[attr-defined]
            resp.raw_blob_uri = raw_blob_uri  # type: ignore[attr-defined]
        results.append(resp)

    return results
