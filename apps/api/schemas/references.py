from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class PolicyReferenceItem(BaseModel):
	model_config = ConfigDict(extra="forbid", from_attributes=True)

	id: uuid.UUID
	reference_type: str
	resolution_status: str
	matched_text: str
	match_offset: Optional[int] = None
	confidence: float
	extractor_version: str

	source_section_id: uuid.UUID
	source_policy_version_id: uuid.UUID

	target_section_id: Optional[uuid.UUID] = None
	target_policy_id: Optional[uuid.UUID] = None
	target_section_title: Optional[str] = None
	target_section_path: Optional[str] = None
	target_policy_name: Optional[str] = None
	target_external_uri: Optional[str] = None
	target_external_label: Optional[str] = None

	created_at: datetime


class SectionReferencesResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	section_id: uuid.UUID
	outbound: List[PolicyReferenceItem]
	inbound: List[PolicyReferenceItem]


class PolicyVersionReferencesResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	policy_version_id: uuid.UUID
	limit: int
	offset: int
	items: List[PolicyReferenceItem]


__all__ = [
	"PolicyReferenceItem",
	"SectionReferencesResponse",
	"PolicyVersionReferencesResponse",
]
