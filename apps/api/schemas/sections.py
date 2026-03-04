from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from packages.db.models.policy_models import PolicySectionResponse


class PolicySectionDetailResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	section_id: uuid.UUID
	tenant_id: uuid.UUID
	policy_id: uuid.UUID
	policy_version_id: uuid.UUID
	policy_name: str
	section_index: int
	section_path: Optional[str] = None
	section_title: Optional[str] = None
	text: str
	effective_date: Optional[date] = None
	is_current: bool
	public_url: Optional[str] = None
	metadata: Dict[str, Any]

__all__ = ["PolicySectionResponse", "PolicySectionDetailResponse"]
