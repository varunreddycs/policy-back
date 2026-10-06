from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.deps import get_repositories
from apps.api.schemas.references import (
	PolicyReferenceItem,
	PolicyVersionReferencesResponse,
	SectionReferencesResponse,
)
from packages.db.repositories.factory import RepositorySet


router = APIRouter(prefix="/v1", tags=["Policies"])


@router.get(
	"/policy-sections/{section_id}/references",
	response_model=SectionReferencesResponse,
	summary="List references for a section",
	description=(
		"Returns outbound (this section -> others) and inbound "
		"(others -> this section) cross-references. Tenant-scoped."
	),
)
def get_section_references(
	section_id: uuid.UUID,
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	direction: str = Query("both", pattern="^(outbound|inbound|both)$"),
	repos: RepositorySet = Depends(get_repositories),
) -> SectionReferencesResponse:
	if not repos.references.section_exists_for_tenant(
		tenant_id=tenant_id, section_id=section_id
	):
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"code": "NOT_FOUND", "message": "Policy section not found"},
		)

	outbound = (
		repos.references.list_outbound_for_section(
			tenant_id=tenant_id, section_id=section_id
		)
		if direction in ("outbound", "both")
		else []
	)
	inbound = (
		repos.references.list_inbound_for_section(
			tenant_id=tenant_id, section_id=section_id
		)
		if direction in ("inbound", "both")
		else []
	)

	return SectionReferencesResponse(
		section_id=section_id,
		outbound=[PolicyReferenceItem.model_validate(r) for r in outbound],
		inbound=[PolicyReferenceItem.model_validate(r) for r in inbound],
	)


@router.get(
	"/policy-versions/{policy_version_id}/references",
	response_model=PolicyVersionReferencesResponse,
	summary="List references for a policy version",
	description="Paginated list of all references whose source belongs to this policy version.",
)
def get_policy_version_references(
	policy_version_id: uuid.UUID,
	tenant_id: uuid.UUID = Query(..., description="Tenant UUID"),
	limit: int = Query(50, ge=1, le=200),
	offset: int = Query(0, ge=0),
	repos: RepositorySet = Depends(get_repositories),
) -> PolicyVersionReferencesResponse:
	if not repos.references.policy_version_exists_for_tenant(
		tenant_id=tenant_id, policy_version_id=policy_version_id
	):
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"code": "NOT_FOUND", "message": "Policy version not found"},
		)

	items = repos.references.list_for_policy_version(
		tenant_id=tenant_id,
		policy_version_id=policy_version_id,
		limit=limit,
		offset=offset,
	)
	return PolicyVersionReferencesResponse(
		policy_version_id=policy_version_id,
		limit=limit,
		offset=offset,
		items=[PolicyReferenceItem.model_validate(r) for r in items],
	)
