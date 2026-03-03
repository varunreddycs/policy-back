from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from deps import get_blob_service, get_policy_query_service
from models.policy_models import PolicyResponse, PolicySectionResponse, PolicyVersionResponse
from services import BlobService
from services.policy_query_service import PolicyQueryService


logger = logging.getLogger(__name__)

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
        # Compute a friendly raw_blob_uri for demos/traceability.
        raw_blob_uri = blob_service.get_blob_uri(version.blob_container, version.blob_name)

        if hasattr(PolicyVersionResponse, "model_validate"):
            resp = PolicyVersionResponse.model_validate(version)  # type: ignore[attr-defined]
            resp = resp.model_copy(update={"raw_blob_uri": raw_blob_uri})  # type: ignore[attr-defined]
        else:  # pragma: no cover
            resp = PolicyVersionResponse.from_orm(version)  # type: ignore[attr-defined]
            resp.raw_blob_uri = raw_blob_uri  # type: ignore[attr-defined]

        results.append(resp)

    return results


@router.get(
    "/policy-versions/{policy_version_id}/sections",
    response_model=List[PolicySectionResponse],
    summary="List extracted sections",
    description="Lists extracted sections for a policy version (tenant-scoped).",
)
def list_policy_version_sections(
    policy_version_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    limit: int = Query(20, ge=1, le=200, description="Max number of sections to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    service: PolicyQueryService = Depends(get_policy_query_service),
) -> List[PolicySectionResponse]:
    return service.list_policy_version_sections(
        tenant_id=tenant_id,
        policy_version_id=policy_version_id,
        limit=limit,
        offset=offset,
    )
