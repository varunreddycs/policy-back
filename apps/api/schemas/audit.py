from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.core.dtos import AnswerResponse, AskRequest


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    correlation_id: Optional[str] = None

    event_type: str
    created_at: datetime

    request: Optional[AskRequest] = None
    response: Optional[AnswerResponse] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class ReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replay_audit_id: UUID
    response: AnswerResponse
