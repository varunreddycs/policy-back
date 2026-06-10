from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.deps import get_policy_query_service
from apps.api.schemas.sections import PolicySectionDetailResponse, PolicySectionResponse
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


@router.get(
    "/policy-sections/{section_id}",
    response_model=PolicySectionDetailResponse,
    summary="Get section detail",
    description="Fetches a specific section with policy/version context (tenant-scoped).",
)
def get_policy_section_detail(
    section_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
    service: PolicyQueryService = Depends(get_policy_query_service),
) -> PolicySectionDetailResponse:
    detail = service.get_policy_section_detail(tenant_id=tenant_id, section_id=section_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Policy section not found"},
        )
    return PolicySectionDetailResponse.model_validate(detail)
