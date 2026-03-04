from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from apps.api.deps import get_policy_query_service
from apps.api.schemas.sections import PolicySectionResponse
from packages.db.policy_query_service import PolicyQueryService


router = APIRouter(prefix="/v1", tags=["Policies"])


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
