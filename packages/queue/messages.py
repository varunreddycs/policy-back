from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExtractPolicyMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="policy.process.requested")
    request_id: str
    policy_version_id: UUID
    correlation_id: Optional[str] = None
    created_at: datetime
    data: Dict[str, Any] = Field(default_factory=dict)
